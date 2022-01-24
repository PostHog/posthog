import re
from typing import Dict, get_args

from drf_spectacular.utils import OpenApiParameter, extend_schema
from numpy import require  # for export
from rest_framework import serializers

from posthog.models.property import OperatorType, Property, PropertyType


class PropertySerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text="Key of the property you're filtering on. For example `email` or `$current_url`"
    )
    value = serializers.CharField(
        help_text='Value of your filter. Can be an array. For example `test@example.com` or `https://example.com/test/`. Can be an array, like `["test@example.com","ok@example.com"]`'
    )
    operator = serializers.ChoiceField(choices=get_args(OperatorType), required=False, default="exact")
    type = serializers.ChoiceField(choices=get_args(PropertyType), default="event", required=False)


class PropertiesSerializer(serializers.Serializer):
    properties = PropertySerializer(required=False, many=True)


class FilterEventSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Name of the event to filter on. For example `$pageview` or `user sign up`.")
    properties = PropertySerializer(many=True, required=False)


class FilterActionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Name of the event to filter on. For example `$pageview` or `user sign up`.")
    properties = PropertySerializer(many=True, required=False)


def preprocess_exclude_path_format(endpoints, **kwargs):
    """
    preprocessing hook that filters out {format} suffixed paths, in case
    format_suffix_patterns is used and {format} path params are unwanted.
    """
    result = []
    for path, path_regex, method, callback in endpoints:
        if hasattr(callback.cls, "legacy_team_compatibility") and callback.cls.legacy_team_compatibility:
            pass
        elif hasattr(callback.cls, "include_in_docs") and callback.cls.include_in_docs:
            path = path.replace("{parent_lookup_team_id}", "{project_id}")
            result.append((path, path_regex, method, callback))
    return result


def custom_postprocessing_hook(result, generator, request, public):
    all_tags = []
    paths: Dict[str, Dict] = {}
    for path, methods in result["paths"].items():
        paths[path] = {}
        for method, definition in methods.items():
            definition["tags"] = [d for d in definition["tags"] if d not in ["projects"]]
            match = re.search(r"((\/api\/(organizations|projects)/{(.*?)}\/)|(\/api\/))(?P<one>[a-zA-Z0-9-_]*)\/", path)
            if match:
                definition["tags"].append(match.group("one"))
                all_tags.append(match.group("one"))
            definition["operationId"] = (
                definition["operationId"].replace("organizations_", "", 1).replace("projects_", "", 1)
            )
            if "parameters" in definition:
                definition["parameters"] = [
                    {
                        "in": "path",
                        "name": "project_id",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.",
                    }
                    if param["name"] == "project_id"
                    else param
                    for param in definition["parameters"]
                ]
            paths[path][method] = definition
    return {
        **result,
        "info": {
            "title": "PostHog API",
            "version": None,
            "description": """
This section of our Docs explains how to pull or push data from/to our API. PostHog has an API available on all tiers of PostHog cloud pricing, including the free tier, and for every self-hosted version.

Please note that PostHog makes use of two different APIs, serving different purposes and using different mechanisms for authentication.

One API is used for pushing data into PostHog. This uses the 'Team API Key' that is included in the [frontend snippet](/docs/integrate/client/js). This API Key is **public**, and is what we use in our frontend integration to push events into PostHog, as well as to check for feature flags, for instance.

The other API is more powerful and allows you to perform any action as if you were an authenticated user utilizing the PostHog UI. It is mostly used for getting data out of PostHog, as well as other private actions such as creating a feature flag. This uses a 'Personal API Key' which you need to create manually (instructions [below](#authentication)). This API Key is **private** and you should not make it public nor share it with anyone. It gives you access to all the data held by your PostHog instance, which includes sensitive information.

These API Docs refer mostly to the **private API**, performing authentication as outlined below. The only exception is the [POST-only public endpoints](/docs/api/post-only-endpoints) section. This section explicitly informs you on how to perform authentication. For endpoints in all other sections, authentication is done as described below.

## Authentication

Personal API keys allow full access to your account, just like e-mail address and password, but you can create any number of them and each one can invalidated individually at any moment. This makes for greater control for you and improved security of stored data.

### How to obtain a personal API key

1. Click on your name/avatar on the top right.
1. Click on 'My account'
1. Navigate to the 'Personal API Keys' section.
1. Click "+ Create a Personal API Key".
1. Give your new key a label – it's just for you, usually to describe the key's purpose.
1. Click 'Create Key'.
1. There you go! At the top of the list you should now be seeing your brand new key. **Immediately** copy its value, as you'll **never** see it again after refreshing the page. But don't worry if you forget to copy it – you can delete and create keys as much as you want.

### How to use a personal API key

There are three options:

1. Use the `Authorization` header and `Bearer` authentication, like so:
    ```JavaScript
    const headers = {
        Authorization: `Bearer ${POSTHOG_PERSONAL_API_KEY}`
    }
    ```
2. Put the key in request body, like so:
    ```JavaScript
    const body = {
        personal_api_key: POSTHOG_PERSONAL_API_KEY
    }
    ```
3. Put the key in query string, like so:
    ```JavaScript
    const url = `https://posthog.example.com/api/event/?personal_api_key=${POSTHOG_PERSONAL_API_KEY}`
    ```

Any one of these methods works, but only the value encountered first (in the order above) will be used for authenticaition!

For PostHog Cloud, use `app.posthog.com` as the host address.

#### Specifying a project when using the API

By default, if you're accessing the API, PostHog will return results from the last project you visited in the UI. To override this behavior, you can pass in your Project API Key (public token) as a query parameter in the request. This ensures you will get data from the project associated with that token.

**Example**

```
api/event/?token=my_project_api_key
```

### cURL example for self-hosted PostHog

```bash
POSTHOG_PERSONAL_API_KEY=qTjsppKJqYLr2YskbsLXmu46eW1oH0r3jZkmKaERlf0

curl \
--header "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \
https://posthog.example.com/api/person/
```

### cURL example for PostHog Cloud

```bash
POSTHOG_PERSONAL_API_KEY=qTjsppKJqYLr2YskbsLXmu46eW1oH0r3jZkmKaERlf0
curl \
--header "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \
https://app.posthog.com/api/person/
```

## Tips

- The [`/users/@me/` endpoint](/docs/api/user) gives you useful information about the current user.
- The `/api/event_definition/` and `/api/property_definition` endpoints provide the possible event names and properties you can use throughout the rest of the API.
- The maximum size of a POST request body is governed by `settings.DATA_UPLOAD_MAX_MEMORY_SIZE`, and is 20MB by default.

## Pagination

Sometimes requests are paginated. If that's the case, it'll be in the following format:

```json
{
    "next": "https://posthog.example.com/api/person/?cursor=cD0yMjgxOTA2",
    "previous": null,
    "results": [
        ...
    ]
}
```

You can then just call the `"next"` URL to get the next set of results.

            """,
        },
        "paths": paths,
        "x-tagGroups": [
            {"name": "Analytics", "tags": ["analytics", "AML", "Customers Timeline"]},
            {"name": "All endpoints", "tags": sorted(list(set(all_tags)))},
        ],
    }
