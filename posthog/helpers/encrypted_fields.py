# Forked from https://github.com/jazzband/django-fernet-encrypted-fields to add a few extra things that are useful for us and
# keep consistency as we also decrypt outside of django

import base64
import json

from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings
from django.core import validators
from django.db import models
from django.db.backends.base.operations import BaseDatabaseOperations
from django.utils.functional import cached_property


class EncryptedFieldMixin(object):
    @cached_property
    def keys(self):
        # NOTE: We previously encrypted some values with the SECRET_KEY which generally speaking we don't want or need to do
        # The SALT_KEY env is rather our list of comma seperated keys that we want to use as our symmetric keys.
        # The SECRET_KEY should only be used for ephemeral data like access tokens

        # First we use the ENCRYPTION_SALT_KEYS env variable to generate keys
        keys = []

        if isinstance(settings.ENCRYPTION_SALT_KEYS, list):
            keys = settings.ENCRYPTION_SALT_KEYS
        elif isinstance(settings.ENCRYPTION_SALT_KEYS, str):
            keys = settings.ENCRYPTION_SALT_KEYS.split(",")

        keys = [key for key in keys if key.strip()]

        # Support for legacy key values
        # TODO: Remove support for these once the migration is complete
        salt_keys = settings.SALT_KEY if isinstance(settings.SALT_KEY, list) else [settings.SALT_KEY]

        # Generate keys for each salt key and secret key
        for salt_key in salt_keys:
            salt = bytes(salt_key, "utf-8")
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend(),
            )
            keys.append(base64.urlsafe_b64encode(kdf.derive(settings.SECRET_KEY.encode("utf-8"))))
        return keys

    @cached_property
    def f(self):
        if len(self.keys) == 1:
            return Fernet(self.keys[0])
        return MultiFernet([Fernet(k) for k in self.keys])

    def get_internal_type(self):
        """
        To treat everything as text
        """
        return "TextField"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value:
            if not isinstance(value, str):
                value = str(value)
            return self.f.encrypt(bytes(value, "utf-8")).decode("utf-8")
        return None

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        if value is None or not isinstance(value, str) or hasattr(self, "_already_decrypted"):
            return value
        try:
            value = self.f.decrypt(bytes(value, "utf-8")).decode("utf-8")
        except InvalidToken:
            pass
        except UnicodeEncodeError:
            pass
        return super(EncryptedFieldMixin, self).to_python(value)

    def clean(self, value, model_instance):
        """
        Create and assign a semaphore so that to_python method will not try to decrypt an already decrypted value
        during cleaning of a form
        """
        self._already_decrypted = True
        ret = super().clean(value, model_instance)
        del self._already_decrypted
        return ret


class EncryptedCharField(EncryptedFieldMixin, models.CharField):
    pass


class EncryptedTextField(EncryptedFieldMixin, models.TextField):
    pass


class EncryptedDateTimeField(EncryptedFieldMixin, models.DateTimeField):
    pass


class EncryptedIntegerField(EncryptedFieldMixin, models.IntegerField):
    @cached_property
    def validators(self):
        # These validators can't be added at field initialization time since
        # they're based on values retrieved from `connection`.
        validators_ = [*self.default_validators, *self._validators]
        internal_type = models.IntegerField().get_internal_type()
        min_value, max_value = BaseDatabaseOperations.integer_field_ranges[internal_type]
        if min_value is not None and not any(
            (
                isinstance(validator, validators.MinValueValidator)
                and (validator.limit_value() if callable(validator.limit_value) else validator.limit_value) >= min_value
            )
            for validator in validators_
        ):
            validators_.append(validators.MinValueValidator(min_value))
        if max_value is not None and not any(
            (
                isinstance(validator, validators.MaxValueValidator)
                and (validator.limit_value() if callable(validator.limit_value) else validator.limit_value) <= max_value
            )
            for validator in validators_
        ):
            validators_.append(validators.MaxValueValidator(max_value))
        return validators_


class EncryptedDateField(EncryptedFieldMixin, models.DateField):
    pass


class EncryptedFloatField(EncryptedFieldMixin, models.FloatField):
    pass


class EncryptedEmailField(EncryptedFieldMixin, models.EmailField):
    pass


class EncryptedBooleanField(EncryptedFieldMixin, models.BooleanField):
    pass


class EncryptedJSONField(EncryptedFieldMixin, models.JSONField):
    def _encrypt_values(self, value):
        if isinstance(value, dict):
            return {key: self._encrypt_values(data) for key, data in value.items()}
        elif isinstance(value, list):
            return [self._encrypt_values(data) for data in value]
        else:
            value = str(value)
        return self.f.encrypt(bytes(value, "utf-8")).decode("utf-8")

    def _decrypt_values(self, value):
        if value is None:
            return value
        if isinstance(value, dict):
            return {key: self._decrypt_values(data) for key, data in value.items()}
        elif isinstance(value, list):
            return [self._decrypt_values(data) for data in value]
        else:
            value = str(value)
        return self.f.decrypt(bytes(value, "utf-8")).decode("utf-8")

    def get_prep_value(self, value):
        return json.dumps(self._encrypt_values(value=value), cls=self.encoder)

    def get_internal_type(self):
        return "JSONField"

    def to_python(self, value):
        if value is None or not isinstance(value, str) or hasattr(self, "_already_decrypted"):
            return value
        try:
            value = self._decrypt_values(value=json.loads(value))
        except InvalidToken:
            pass
        except UnicodeEncodeError:
            pass
        return super(EncryptedFieldMixin, self).to_python(value)


class EncryptedJSONStringField(EncryptedFieldMixin, models.JSONField):
    """
    This is an alternative class option that encrypts the value to a simple string rather than a JSON object.
    This means you can only decrypt / encrypt the entire object but that is fine for most use cases.
    """

    def get_prep_value(self, value):
        if not value:
            return None
        # Here we just want to json dump the value to a string
        stringified_value = json.dumps(value, cls=self.encoder)
        return super().get_prep_value(stringified_value)

    def to_python(self, value):
        if hasattr(self, "_already_decrypted"):
            return value

        value = super().to_python(value)

        if value:
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass

        return value
