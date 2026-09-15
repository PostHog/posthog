from enum import Enum


class AccountPropertyPinKind(str, Enum):
    CUSTOM_PROPERTY = "custom_property"
    RELATIONSHIP = "relationship"
