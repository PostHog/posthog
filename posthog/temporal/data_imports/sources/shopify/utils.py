from typing import Any


class ShopifyGraphQLObject:
    def __init__(self, name: str, query: str, permissions_query: str | None = None):
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
        ref = ref.get(key, None)
        if ref is None:
            return payload, False
    return ref, True
