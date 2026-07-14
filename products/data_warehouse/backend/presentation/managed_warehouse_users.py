"""Serializers for the managed warehouse DB user endpoints.

See `products/data_warehouse/backend/presentation/views/managed_warehouse_users.py` for the
duckgres adapter these back. Duckgres is the source of truth for DB user state — these
serializers only shape what the ViewSet actions proxy back from (or generate for) it.
"""

from rest_framework import serializers


class ManagedWarehouseUserSerializer(serializers.Serializer):
    username = serializers.CharField(help_text="Database username.")
    disabled = serializers.BooleanField(help_text="Whether the user is currently blocked from connecting.")
    created_at = serializers.DateTimeField(help_text="When the user was created.")
    updated_at = serializers.DateTimeField(help_text="When the user was last updated.")


class ManagedWarehouseUserConnectionSerializer(serializers.Serializer):
    host = serializers.CharField(help_text="Connection host for the managed warehouse.")
    port = serializers.IntegerField(help_text="Postgres wire-protocol port.")
    database = serializers.CharField(help_text="Database to connect to — always 'ducklake'.")
    username = serializers.CharField(help_text="The database username to connect with.")


class CreateManagedWarehouseUserRequestSerializer(serializers.Serializer):
    username = serializers.CharField(
        help_text="Username for the new database user. Lowercase letters, numbers, and "
        "underscores only, starting with a letter, 3-63 characters."
    )


class ManagedWarehouseUserCredentialsResponseSerializer(serializers.Serializer):
    username = serializers.CharField(help_text="Database username.")
    password = serializers.CharField(
        help_text="Plaintext password for the new user — shown only in this response and never persisted or shown again."
    )
    connection = ManagedWarehouseUserConnectionSerializer(
        allow_null=True,
        help_text="Ready-to-use connection details for this user. Null if the managed warehouse "
        "hasn't finished provisioning.",
    )


class ResetManagedWarehouseUserPasswordResponseSerializer(serializers.Serializer):
    username = serializers.CharField(help_text="Database username.")
    password = serializers.CharField(
        help_text="New plaintext password — shown only in this response and never persisted or shown again."
    )


class DeleteManagedWarehouseUserResponseSerializer(serializers.Serializer):
    deleted = serializers.CharField(help_text="Username of the database user that was deleted.")


class DisableManagedWarehouseUserResponseSerializer(serializers.Serializer):
    disabled = serializers.BooleanField(help_text="Whether the user is now blocked from connecting.")
    killed = serializers.IntegerField(help_text="Number of the user's live sessions that were terminated.")
    cp_responders = serializers.IntegerField(help_text="Number of control-plane replicas that confirmed the disable.")
    cp_total = serializers.IntegerField(help_text="Total number of control-plane replicas in the cluster.")


class EnableManagedWarehouseUserResponseSerializer(serializers.Serializer):
    disabled = serializers.BooleanField(help_text="Whether the user is still blocked from connecting (false).")
    cp_responders = serializers.IntegerField(help_text="Number of control-plane replicas that confirmed the enable.")
    cp_total = serializers.IntegerField(help_text="Total number of control-plane replicas in the cluster.")
