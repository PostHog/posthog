from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, JsonResponse

# Keep in sync with productionAppIds and the variant suffixes in products/mobile/src/lib/appVariants.json.
IOS_BUNDLE_IDS = ("com.posthog.code.mobile", "com.posthog.code.mobile.preview", "com.posthog.code.mobile.dev")
ANDROID_PACKAGE_NAMES = ("com.posthog.mobile", "com.posthog.mobile.preview", "com.posthog.mobile.dev")
# Keep in sync with the Android intent filter in products/mobile/app.config.ts and webLinkTarget() in
# products/mobile/src/lib/deepLinkKind.ts. A path listed here that the app cannot route opens an empty screen.
APP_LINK_PATHS = ("/project/*/inbox/reports/*",)
_CACHE_MAX_AGE_SECONDS = 3600


def _json(body: dict | list) -> HttpResponse:
    response = JsonResponse(body, safe=False)
    response["Cache-Control"] = f"public, max-age={_CACHE_MAX_AGE_SECONDS}"
    return response


def apple_app_site_association(request: HttpRequest) -> HttpResponse:
    """
    iOS opens matching links in the app only when this file is served directly, with no redirect.

    https://developer.apple.com/documentation/xcode/supporting-associated-domains
    """
    team_id = settings.MOBILE_APP_APPLE_TEAM_ID
    if not team_id:
        return HttpResponseNotFound()
    return _json(
        {
            "applinks": {
                "details": [
                    {
                        "appIDs": [f"{team_id}.{bundle_id}" for bundle_id in IOS_BUNDLE_IDS],
                        "components": [{"/": path} for path in APP_LINK_PATHS],
                    }
                ]
            }
        }
    )


def android_asset_links(request: HttpRequest) -> HttpResponse:
    """
    Android verifies the app's `autoVerify` intent filters against this file.

    https://developer.android.com/training/app-links/verify-android-applinks
    """
    fingerprints = settings.MOBILE_APP_ANDROID_CERT_FINGERPRINTS
    if not fingerprints:
        return HttpResponseNotFound()
    return _json(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": package_name,
                    "sha256_cert_fingerprints": list(fingerprints),
                },
            }
            for package_name in ANDROID_PACKAGE_NAMES
        ]
    )
