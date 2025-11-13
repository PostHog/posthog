from typing import Any
from uuid import uuid4


class ShopifyGraphQLObject:
    def __init__(
        self,
        name: str,
        query: str,
        display_name: str | None = None,
        permissions_query: str | None = None,
    ):
        # shopify graphql responses typically look like this:
        # {
        #   data {
        #     shopifyObject {
        #       nodes {
        #         ...
        #       }
        #     }
        #   }
        # }
        #
        # where shopifyObject is something real like abandonedCheckouts. sometimes the shopifyObject is wrapped in
        # a parent object like shopifyPaymentsAccount. the "name" attribute of this class is meant to be a dot
        # separated path that can be traversed to get to the nodes property in a shopify graphql response. it follows
        # the form [parentObject.]shopifyObject where the parentObject(s) are optional / could be nested, etc. importantly,
        # it excludes `data` and `nodes`.
        self.name: str = name
        self.query: str = query
        # optional display name for cases where the shopify name makes less sense to users
        self.display_name: str | None = display_name
        self.permissions_query: str | None = permissions_query


def unwrap(payload: Any, path: str):
    """Drill down into a graphql response payload with intentionally unsafe key lookup.

    The path argument does not follow the same convention as ShopifyGraphQLObject.name. It will be
    taken as-is.
    """
    keys = path.split(".")
    ref = payload
    for key in keys:
        ref = ref[key]
    return ref


def safe_unwrap(payload: Any, path: str):
    """Drill down into a graphql response payload with safe key lookup.

    Returns data from within the payload and a boolean indicating whether the lookup succeeded.
    If not, the unmodified payload is returned. The path argument does not follow the same convention as
    ShopifyGraphQLObject.name. It will be taken as-is.
    """
    keys = path.split(".")
    ref = payload
    for key in keys:
        if not isinstance(ref, dict):
            return payload, False
        ref = ref.get(key, None)
        if ref is None:
            return payload, False
    return ref, True


def safe_set(payload: Any, path: str, value: Any):
    """Drill down into a graphql response payload with safe key lookup and then set a value there only if it doesn't overwrite"""
    # we use a sentinel to differentiate between when a key is truly unset vs
    # when a key is present but the value is None
    uuid = uuid4()
    sentinel = f"sentinel_{uuid}"
    keys = path.split(".")
    ref = payload
    for i, key in enumerate(keys):
        if not isinstance(ref, dict):
            break

        tmp = ref.get(key, sentinel)
        is_final_key = i == len(keys) - 1

        if tmp == sentinel:
            if is_final_key:
                ref[key] = value
            else:
                ref[key] = {}
            ref = ref[key]
        else:
            ref = tmp
    return payload
