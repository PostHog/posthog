import re
from typing import Literal, NotRequired, TypedDict


class CoreFilterDefinition(TypedDict):
    """Like the CoreFilterDefinition type in the frontend, except no JSX.Element allowed."""

    label: str
    label_llm: NotRequired[str]
    description: NotRequired[str]
    description_llm: NotRequired[str]
    examples: NotRequired[list[str | int | float]]
    system: NotRequired[bool]
    type: NotRequired[Literal["String", "Numeric", "DateTime", "Boolean"]]
    ignored_in_assistant: NotRequired[bool]
    virtual: NotRequired[bool]
    used_for_debug: NotRequired[bool]


"""
Same as https://github.com/PostHog/posthog-js/blob/master/src/utils/event-utils.ts
Ideally this would be imported from one place.
"""
CAMPAIGN_PROPERTIES: list[str] = [
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "gclid",  # google ads
    "gad_source",  # google ads
    "gclsrc",  # google ads 360
    "dclid",  # google display ads
    "gbraid",  # google ads, web to app
    "wbraid",  # google ads, app to web
    "fbclid",  # facebook
    "msclkid",  # microsoft
    "twclid",  # twitter
    "li_fat_id",  # linkedin
    "mc_cid",  # mailchimp campaign id
    "igshid",  # instagram
    "ttclid",  # tiktok
    "rdt_cid",  # reddit
    "epik",  # pinterest
    "qclid",  # quora
    "sccid",  # snapchat
    "irclid",  # impact
    "_kx",  # klaviyo
]

PERSON_PROPERTIES_ADAPTED_FROM_EVENT: set[str] = {
    "$app_build",
    "$app_name",
    "$app_namespace",
    "$app_version",
    "$browser",
    "$browser_version",
    "$device_type",
    "$current_url",
    "$pathname",
    "$os",
    "$os_version",
    "$referring_domain",
    "$referrer",
    "$screen_height",
    "$screen_width",
    "$viewport_height",
    "$viewport_width",
    "$raw_user_agent",
    *CAMPAIGN_PROPERTIES,
}

SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS = {
    "$referring_domain",
    "utm_source",
    "utm_campaign",
    "utm_medium",
    "utm_content",
    "utm_term",
    "gclid",
    "gad_source",
    "gclsrc",
    "dclid",
    "gbraid",
    "wbraid",
    "fbclid",
    "msclkid",
    "twclid",
    "li_fat_id",
    "mc_cid",
    "igshid",
    "ttclid",
    "rdt_cid",
    "epik",
    "qclid",
    "sccid",
    "irclid",
    "_kx",
}

SESSION_PROPERTIES_ALSO_INCLUDED_IN_EVENTS = {
    "$current_url",  # Gets renamed to just $url
    "$host",
    "$pathname",
    "$referrer",
    *SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS,
}

# IF UPDATING THIS, ALSO RUN `pnpm run taxonomy:build` to update core-filter-definitions-by-group.json
CORE_FILTER_DEFINITIONS_BY_GROUP: dict[str, dict[str, CoreFilterDefinition]] = {
    "events": {
        # in front end this key is the empty string
        "All events": {
            "label": "All events",
            "description": "This is a wildcard that matches all events.",
        },
        "$pageview": {
            "label": "Pageview",
            "description": "When a user loads (or reloads) a page.",
        },
        "$pageleave": {
            "label": "Pageleave",
            "description": "When a user leaves a page.",
            "ignored_in_assistant": True,  # Pageleave confuses the LLM, it just can't use this event in a sensible way
        },
        "$autocapture": {
            "label": "Autocapture",
            "description": "User interactions that were automatically captured.",
            "examples": ["clicked button"],
            "ignored_in_assistant": True,  # Autocapture is only useful with autocapture-specific filters, which the LLM isn't adept at yet
        },
        "$$heatmap": {
            "label": "Heatmap",
            "description": "Heatmap events carry heatmap data to the backend, they do not contribute to event counts.",
            "ignored_in_assistant": True,  # Heatmap events are not useful for LLM
        },
        "$copy_autocapture": {
            "label": "Clipboard autocapture",
            "description": "Selected text automatically captured when a user copies or cuts.",
            "ignored_in_assistant": True,  # Too niche
        },
        "$screen": {
            "label": "Screen",
            "description": "When a user loads a screen in a mobile app.",
        },
        "$set": {
            "label": "Set person properties",
            "description": "Setting person properties. Sent as `$set`.",
            "ignored_in_assistant": True,
        },
        "$opt_in": {
            "label": "Opt in",
            "description": "When a user opts into analytics.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$feature_flag_called": {
            "label": "Feature flag called",
            "description": (
                'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag event. If you want to filter other events, try "Active feature flags".'
            ),
            "examples": ["beta-feature"],
            "ignored_in_assistant": True,  # Mostly irrelevant product-wise
        },
        "$feature_view": {
            "label": "Feature view",
            "description": "When a user views a feature.",
            "ignored_in_assistant": True,  # Specific to posthog-js/react, niche
        },
        "$feature_interaction": {
            "label": "Feature interaction",
            "description": "When a user interacts with a feature.",
            "ignored_in_assistant": True,  # Specific to posthog-js/react, niche
        },
        "$feature_enrollment_update": {
            "label": "Feature enrollment",
            "description": "When a user enrolls with a feature.",
            "description_llm": "When a user opts in or out of a beta feature. This event is specific to the PostHog Early Access Features product, and is only relevant if the project is using this product.",
        },
        "$capture_metrics": {
            "label": "Capture metrics",
            "description": "Metrics captured with values pertaining to your systems at a specific point in time.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$identify": {
            "label": "Identify",
            "description": "A user has been identified with properties.",
            "description_llm": "Identifies an anonymous user. The event shows how many users used an account, so do not use it for active users metrics because a user may skip identification.",
        },
        "$create_alias": {
            "label": "Alias",
            "description": "An alias ID has been added to a user.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$merge_dangerously": {
            "label": "Merge",
            "description": "An alias ID has been added to a user.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$groupidentify": {
            "label": "Group identify",
            "description": "A group has been identified with properties.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$rageclick": {
            "label": "Rageclick",
            "description": "A user has rapidly and repeatedly clicked in a single place.",
        },
        "$dead_click": {
            "label": "Dead click",
            "description": "A user has clicked on something that is probably not clickable.",
        },
        "$exception": {
            "label": "Exception",
            "description": "An unexpected error or unhandled exception in your application.",
        },
        "$web_vitals": {
            "label": "Web vitals",
            "description": "Automatically captured web vitals data.",
        },
        "$ai_generation": {
            "label": "AI generation (LLM)",
            "description": "A call to an LLM model. Contains the input prompt, output, model used and costs.",
        },
        "$ai_evaluation": {
            "label": "AI evaluation (LLM)",
            "description": "An evaluation of an AI event. Contains the result of the evaluation, the target event, and the evaluation metadata.",
        },
        "$ai_metric": {
            "label": "AI metric (LLM)",
            "description": "An evaluation metric for a trace of a generative AI model (LLM). Contains the trace ID, metric name, and metric value.",
        },
        "$ai_feedback": {
            "label": "AI feedback (LLM)",
            "description": "User-provided feedback for a trace of a generative AI model (LLM).",
        },
        "$ai_trace": {
            "label": "AI trace (LLM)",
            "description": "A generative AI trace. Usually a trace tracks a single user interaction and contains one or more AI generation calls.",
        },
        "$ai_span": {
            "label": "AI span (LLM)",
            "description": "A generative AI span. Usually a span tracks a unit of work for a trace of generative AI models (LLMs).",
        },
        "$ai_embedding": {
            "label": "AI embedding (LLM)",
            "description": "A call to an embedding model.",
        },
        "$csp_violation": {
            "label": "CSP violation",
            "description": "Content Security Policy violation reported by a browser to our csp endpoint.",
            "examples": ["Unauthorized inline script", "Trying to load resources from unauthorized domain"],
        },
        "Application opened": {
            "label": "Application opened",
            "description": "When a user opens the mobile app either for the first time or from the foreground.",
        },
        "Application backgrounded": {
            "label": "Application backgrounded",
            "description": "When a user puts the mobile app in the background.",
        },
        "Application updated": {
            "label": "Application updated",
            "description": "When a user upgrades the mobile app.",
        },
        "Application installed": {
            "label": "Application installed",
            "description": "When a user installs the mobile app.",
        },
        "Application became active": {
            "label": "Application became active",
            "description": "When a user puts the mobile app in the foreground.",
        },
        "Deep link opened": {
            "label": "Deep link opened",
            "description": "When a user opens the mobile app via a deep link.",
        },
    },
    "elements": {
        "tag_name": {
            "label": "Tag name",
            "description": "HTML tag name of the element which you want to filter.",
            "examples": ["a", "button", "input"],
        },
        "selector": {
            "label": "CSS selector",
            "description": "Select any element by CSS selector.",
            "examples": ["div > a", "table td:nth-child(2)", ".my-class"],
        },
        "text": {
            "label": "Text",
            "description": "Filter on the inner text of the HTML element.",
        },
        "href": {
            "label": "Target (href)",
            "description": "Filter on the `href` attribute of the element.",
            "examples": ["https://posthog.com/about"],
        },
    },
    "metadata": {
        "distinct_id": {
            "label": "Distinct ID",
            "description": "The current distinct ID of the user.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
        "timestamp": {
            "label": "Timestamp",
            "description": "Time the event happened.",
            "examples": ["2023-05-20T15:30:00Z"],
            "system": True,
            "ignored_in_assistant": True,  # Timestamp is not a filterable property
        },
        "event": {
            "label": "Event",
            "description": "The name of the event.",
            "examples": ["$pageview"],
            "system": True,
            "ignored_in_assistant": True,
        },
        "person_id": {
            "label": "Person ID",
            "description": "The ID of the person, depending on the person properties mode.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
        "person_mode": {
            "label": "Person mode",
            "description": "The person mode determined during ingestion: full (identified user with properties), propertyless (anonymous user), or force_upgrade (anonymous event linked to an already identified user). Used in usage reports.",
            "examples": ["full", "propertyless", "force_upgrade"],
            "system": True,
            "ignored_in_assistant": True,
        },
    },
    "event_properties": {
        "$session_recording_masking": {
            "label": "Replay config - masking",
            "description": "The masking configuration for the session recording.",
            "type": "String",
            "used_for_debug": True,
        },
        "$sdk_debug_session_start": {
            "label": "Session start",
            "description": "The timestamp of the session start for the current session id. Not necessarily the same as SDK init time.",
            "type": "Numeric",
            "used_for_debug": True,
        },
        "$sdk_debug_current_session_duration": {
            "label": "Current session duration",
            "description": "The current session duration in milliseconds.",
            "type": "Numeric",
            "used_for_debug": True,
        },
        "$sdk_debug_replay_event_trigger_status": {
            "label": "event trigger status",
            "description": "The status of the recording event trigger.",
            "examples": ["trigger_disabled", "trigger_pending", "trigger_matched"],
            "type": "String",
            "used_for_debug": True,
        },
        "$sdk_debug_replay_linked_flag_trigger_status": {
            "label": "linked flag trigger status",
            "description": "The status of the linked flag trigger.",
            "examples": ["trigger_disabled", "trigger_pending", "trigger_matched"],
            "type": "String",
            "used_for_debug": True,
        },
        "$sdk_debug_replay_remote_trigger_matching_config": {
            "label": "remote trigger matching config",
            "description": "Whether to match on all or any triggers.",
            "examples": ["all", "any"],
            "type": "String",
            "used_for_debug": True,
        },
        "$sdk_debug_replay_url_trigger_status": {
            "label": "URL trigger status",
            "description": "The status of the recording url trigger.",
            "examples": ["trigger_disabled", "trigger_pending", "trigger_matched"],
            "type": "String",
            "used_for_debug": True,
        },
        "$sess_rec_flush_size": {
            "label": "Estimated bytes flushed",
            "description": "Estimated size in bytes of flushed recording data so far in this session. Added to events as a debug property.",
            "type": "Numeric",
            "used_for_debug": True,
        },
        "$session_recording_remote_config": {
            "label": "Session recording remote config received",
            "description": "The remote config for session recording received from the server (or loaded from storage).",
            "used_for_debug": True,
        },
        "$initialization_time": {
            "label": "initialization time",
            "description": "The iso formatted timestamp of SDK initialization.",
            "type": "String",
            "used_for_debug": True,
        },
        "$transformations_skipped": {
            "label": "Transformations skipped",
            "description": "Array of transformations skipped during ingestion.",
            "used_for_debug": True,
        },
        "$transformations_succeeded": {
            "label": "Transformations succeeded",
            "description": "Array of transformations that succeeded during ingestion.",
            "used_for_debug": True,
        },
        "$config_defaults": {
            "label": "Config defaults",
            "description": "The version of the PostHog config defaults that were used when capturing the event.",
            "type": "String",
            "used_for_debug": True,
        },
        "$python_runtime": {
            "label": "Python runtime",
            "description": "The Python runtime that was used to capture the event.",
            "examples": ["CPython"],
            "system": True,
            "ignored_in_assistant": True,
        },
        "$python_version": {
            "label": "Python version",
            "description": "The Python version that was used to capture the event.",
            "examples": ["3.11.5"],
            "system": True,
            "ignored_in_assistant": True,
        },
        "$sdk_debug_replay_internal_buffer_length": {
            "label": "Replay internal buffer length",
            "description": "Useful for debugging. The internal buffer length for replay.",
            "examples": ["100"],
            "system": True,
            "ignored_in_assistant": True,
            "used_for_debug": True,
        },
        "$sdk_debug_replay_internal_buffer_size": {
            "label": "Replay internal buffer size",
            "description": "Useful for debugging. The internal buffer size for replay.",
            "examples": ["100"],
            "system": True,
            "ignored_in_assistant": True,
            "used_for_debug": True,
        },
        "$sdk_debug_retry_queue_size": {
            "label": "Retry queue size",
            "description": "Useful for debugging. The size of the retry queue.",
            "examples": ["100"],
            "system": True,
            "ignored_in_assistant": True,
            "used_for_debug": True,
        },
        "$last_posthog_reset": {
            "label": "Timestamp of last call to `Reset` in the web sdk",
            "description": "The timestamp of the last call to `Reset` in the web SDK. This can be useful for debugging.",
            "ignored_in_assistant": True,
            "system": True,
            "used_for_debug": True,
        },
        # do we need distinct_id and $session_duration here in the back end?
        "$copy_type": {
            "label": "Copy type",
            "description": "Type of copy event.",
            "examples": ["copy", "cut"],
            "ignored_in_assistant": True,
        },
        "$selected_content": {
            "label": "Copied content",
            "description": "The content that was selected when the user copied or cut.",
            "ignored_in_assistant": True,
        },
        "$set": {
            "label": "Set person properties",
            "description": "Person properties to be set. Sent as `$set`.",
            "ignored_in_assistant": True,
        },
        "$set_once": {
            "label": "Set person properties once",
            "description": "Person properties to be set if not set already (i.e. first-touch). Sent as `$set_once`.",
            "ignored_in_assistant": True,
        },
        "$pageview_id": {
            "label": "Pageview ID",
            "description": "PostHog's internal ID for matching events to a pageview.",
            "system": True,
            "ignored_in_assistant": True,
        },
        "$autocapture_disabled_server_side": {
            "label": "Autocapture disabled server-side",
            "description": "If autocapture has been disabled server-side.",
            "system": True,
            "ignored_in_assistant": True,
        },
        "$console_log_recording_enabled_server_side": {
            "label": "Console log recording enabled server-side",
            "description": "If console log recording has been enabled server-side.",
            "system": True,
            "ignored_in_assistant": True,
        },
        "$session_entry__kx": {
            "description": "Klaviyo Tracking ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry _kx",
            "ignored_in_assistant": True,
        },
        "$session_entry_dclid": {
            "description": "DoubleClick ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry dclid",
            "ignored_in_assistant": True,
        },
        "$session_entry_epik": {
            "description": "Pinterest Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry epik",
            "ignored_in_assistant": True,
        },
        "$session_entry_fbclid": {
            "description": "Facebook Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry fbclid",
            "ignored_in_assistant": True,
        },
        "$session_entry_gad_source": {
            "description": "Google Ads Source Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry gad_source",
            "ignored_in_assistant": True,
        },
        "$session_entry_gbraid": {
            "description": "Google Ads, web to app Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry gbraid",
            "ignored_in_assistant": True,
        },
        "$session_entry_gclid": {
            "description": "Google Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry gclid",
            "ignored_in_assistant": True,
        },
        "$session_entry_gclsrc": {
            "description": "Google Click Source Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry gclsrc",
            "ignored_in_assistant": True,
        },
        "$session_entry_host": {
            "description": "The hostname of the Current URL. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["example.com", "localhost:8000"],
            "label": "Session entry Host",
            "ignored_in_assistant": True,
        },
        "$session_entry_igshid": {
            "description": "Instagram Share ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry igshid",
            "ignored_in_assistant": True,
        },
        "$session_entry_irclid": {
            "description": "Impact Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry irclid",
            "ignored_in_assistant": True,
        },
        "$session_entry_li_fat_id": {
            "description": "LinkedIn First-Party Ad Tracking ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry li_fat_id",
            "ignored_in_assistant": True,
        },
        "$session_entry_mc_cid": {
            "description": "Mailchimp Campaign ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry mc_cid",
            "ignored_in_assistant": True,
        },
        "$session_entry_msclkid": {
            "description": "Microsoft Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry msclkid",
            "ignored_in_assistant": True,
        },
        "$session_entry_pathname": {
            "description": "The path of the Current URL, which means everything in the url after the domain. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["/pricing", "/about-us/team"],
            "label": "Session entry Path name",
            "ignored_in_assistant": True,
        },
        "$session_entry_qclid": {
            "description": "Quora Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry qclid",
            "ignored_in_assistant": True,
        },
        "$session_entry_rdt_cid": {
            "description": "Reddit Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry rdt_cid",
            "ignored_in_assistant": True,
        },
        "$session_entry_referrer": {
            "description": "URL of where the user came from. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["https://google.com/search?q=posthog&rlz=1C..."],
            "label": "Session entry Referrer URL",
            "ignored_in_assistant": True,
        },
        "$session_entry_referring_domain": {
            "description": "Domain of where the user came from. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["google.com", "facebook.com"],
            "label": "Session entry Referring domain",
            "ignored_in_assistant": True,
        },
        "$session_entry_sccid": {
            "description": "Snapchat Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry sccid",
            "ignored_in_assistant": True,
        },
        "$session_entry_ttclid": {
            "description": "TikTok Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry ttclid",
            "ignored_in_assistant": True,
        },
        "$session_entry_twclid": {
            "description": "Twitter Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry twclid",
            "ignored_in_assistant": True,
        },
        "$session_entry_url": {
            "description": "The URL visited at the time of the event. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["https://example.com/interesting-article?parameter=true"],
            "label": "Session entry Current URL",
            "ignored_in_assistant": True,
        },
        "$session_entry_utm_campaign": {
            "description": "UTM campaign tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["feature launch", "discount"],
            "label": "Session entry UTM campaign",
            "ignored_in_assistant": True,
        },
        "$session_entry_utm_content": {
            "description": "UTM content tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["bottom link", "second button"],
            "label": "Session entry UTM content",
            "ignored_in_assistant": True,
        },
        "$session_entry_utm_medium": {
            "description": "UTM medium tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["Social", "Organic", "Paid", "Email"],
            "label": "Session entry UTM medium",
            "ignored_in_assistant": True,
        },
        "$session_entry_utm_source": {
            "description": "UTM source tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
            "label": "Session entry UTM source",
            "ignored_in_assistant": True,
        },
        "$session_entry_utm_term": {
            "description": "UTM term tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["free goodies"],
            "label": "Session entry UTM term",
            "ignored_in_assistant": True,
        },
        "$session_entry_wbraid": {
            "description": "Google Ads, app to web Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry wbraid",
            "ignored_in_assistant": True,
        },
        "$session_recording_recorder_version_server_side": {
            "label": "Session recording recorder version server-side",
            "description": "The version of the session recording recorder that is enabled server-side.",
            "examples": ["v2"],
            "system": True,
            "ignored_in_assistant": True,
            "used_for_debug": True,
        },
        "$session_is_sampled": {
            "label": "Whether the session is sampled",
            "description": "Whether the session is sampled for session recording.",
            "examples": ["true", "false"],
            "system": True,
            "ignored_in_assistant": True,
            "used_for_debug": True,
        },
        "$feature_flag_payloads": {
            "label": "Feature flag payloads",
            "description": "Feature flag payloads active in the environment.",
            "ignored_in_assistant": True,
        },
        "$capture_failed_request": {
            "label": "Capture failed request",
            "description": "",
            "ignored_in_assistant": True,
        },
        "$lib_rate_limit_remaining_tokens": {
            "label": "Clientside rate limit remaining tokens",
            "description": "Remaining rate limit tokens for the posthog-js library client-side rate limiting implementation.",
            "examples": ["100"],
            "ignored_in_assistant": True,
            "used_for_debug": True,
        },
        "token": {
            "label": "Token",
            "description": "Token used for authentication.",
            "examples": ["ph_abcdefg"],
            "ignored_in_assistant": True,
        },
        "$exception_types": {
            "label": "Exception type",
            "description": "The type of the exception.",
            "examples": ["TypeError"],
        },
        "$exception_functions": {
            "label": "Exception function",
            "description": "A function contained in the exception.",
        },
        "$exception_values": {"label": "Exception message", "description": "The description of the exception."},
        "$exception_sources": {"label": "Exception source", "description": "A source file included in the exception."},
        "$exception_list": {
            "label": "Exception list",
            "description": "List of one or more associated exceptions.",
            "system": True,
        },
        "$exception_level": {
            "label": "Exception level",
            "description": "Exception categorized by severity.",
            "examples": ["error"],
        },
        "$exception_type": {
            "label": "Exception type",
            "description": "Exception categorized into types.",
            "examples": ["Error"],
        },
        "$exception_message": {
            "label": "Exception message",
            "description": "The message detected on the error.",
        },
        "$exception_fingerprint": {
            "label": "Exception fingerprint",
            "description": "A fingerprint used to group issues, can be set clientside.",
        },
        "$exception_proposed_fingerprint": {
            "label": "Exception proposed fingerprint",
            "description": "The fingerprint used to group issues. Auto generated unless provided clientside.",
        },
        "$exception_issue_id": {
            "label": "Exception issue ID",
            "description": "The id of the issue the fingerprint was associated with at ingest time.",
        },
        "$exception_source": {
            "label": "Exception source",
            "description": "The source of the exception.",
            "examples": ["JS file"],
        },
        "$exception_lineno": {
            "label": "Exception source line number",
            "description": "Which line in the exception source that caused the exception.",
        },
        "$exception_colno": {
            "label": "Exception source column number",
            "description": "Which column of the line in the exception source that caused the exception.",
        },
        "$exception_DOMException_code": {
            "label": "DOMException code",
            "description": "If a DOMException was thrown, it also has a DOMException code.",
        },
        "$exception_is_synthetic": {
            "label": "Exception is synthetic",
            "description": "Whether this was detected as a synthetic exception.",
        },
        "$exception_stack_trace_raw": {
            "label": "Exception raw stack trace",
            "description": "The exceptions stack trace, as a string.",
        },
        "$exception_handled": {
            "label": "Exception was handled",
            "description": "Whether this was a handled or unhandled exception.",
        },
        "$exception_personURL": {
            "label": "Exception person URL",
            "description": "The PostHog person that experienced the exception.",
        },
        "$cymbal_errors": {
            "label": "Exception processing errors",
            "description": "Errors encountered while trying to process exceptions.",
            "system": True,
        },
        "$exception_capture_endpoint": {
            "label": "Exception capture endpoint",
            "description": "Endpoint used by posthog-js exception autocapture.",
            "examples": ["/e/"],
        },
        "$exception_capture_endpoint_suffix": {
            "label": "Exception capture endpoint suffix",
            "description": "Endpoint used by posthog-js exception autocapture.",
            "examples": ["/e/"],
        },
        "$exception_capture_enabled_server_side": {
            "label": "Exception capture enabled server side",
            "description": "Whether exception autocapture was enabled in remote config.",
        },
        "$ce_version": {
            "label": "$ce_version",
            "description": "",
            "system": True,
        },
        "$anon_distinct_id": {
            "label": "Anon distinct ID",
            "description": "If the user was previously anonymous, their anonymous ID will be set here.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
            "system": True,
        },
        "$event_type": {
            "label": "Event type",
            "description": "When the event is an $autocapture event, this specifies what the action was against the element.",
            "examples": ["click", "submit", "change"],
        },
        "$insert_id": {
            "label": "Insert ID",
            "description": "Unique insert ID for the event.",
            "system": True,
        },
        "$time": {
            "label": "$time (deprecated)",
            "description": "Use the SQL field `timestamp` instead. This field was previously set on some client side events.",
            "system": True,
            "examples": ["1681211521.345"],
        },
        "$browser_type": {
            "label": "Browser type",
            "description": "This is only added when posthog-js config.opt_out_useragent_filter is true.",
            "examples": ["browser", "bot"],
        },
        "$device_id": {
            "label": "Device ID",
            "description": "Unique ID for that device, consistent even if users are logging in/out.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
            "system": True,
        },
        "$replay_minimum_duration": {
            "label": "Replay config - minimum duration",
            "description": "Config for minimum duration before emitting a session recording.",
            "examples": ["1000"],
            "system": True,
            "used_for_debug": True,
        },
        "$replay_sample_rate": {
            "label": "Replay config - sample rate",
            "description": "Config for sampling rate of session recordings.",
            "examples": ["0.1"],
            "system": True,
            "used_for_debug": True,
        },
        "$session_recording_start_reason": {
            "label": "Session recording start reason",
            "description": "Reason for starting the session recording. Useful for e.g. if you have sampling enabled and want to see on batch exported events which sessions have recordings available.",
            "examples": ["sampling_override", "recording_initialized", "linked_flag_match"],
            "system": True,
            "used_for_debug": True,
        },
        "$session_recording_canvas_recording": {
            "label": "Session recording canvas recording",
            "description": "Session recording canvas capture config.",
            "examples": ['{"enabled": false}'],
            "system": True,
            "used_for_debug": True,
        },
        "$session_recording_network_payload_capture": {
            "label": "Session recording network payload capture",
            "description": "Session recording network payload capture config.",
            "examples": ['{"recordHeaders": false}'],
            "system": True,
            "used_for_debug": True,
        },
        "$configured_session_timeout_ms": {
            "label": "Configured session timeout",
            "description": "Configured session timeout in milliseconds.",
            "examples": ["1800000"],
            "system": True,
            "used_for_debug": True,
        },
        "$replay_script_config": {
            "label": "Replay script config",
            "description": "Sets an alternative recorder script for the web sdk.",
            "examples": ['{"script": "recorder-next"}'],
            "system": True,
            "used_for_debug": True,
        },
        "$session_recording_url_trigger_activated_session": {
            "label": "Session recording URL trigger activated session",
            "description": "Session recording URL trigger activated session config. Used by posthog-js to track URL activation of session replay.",
            "system": True,
            "used_for_debug": True,
        },
        "$session_recording_url_trigger_status": {
            "label": "Session recording URL trigger status",
            "description": "Session recording URL trigger status. Used by posthog-js to track URL activation of session replay.",
            "system": True,
            "used_for_debug": True,
        },
        "$recording_status": {
            "label": "Session recording status",
            "description": "The status of session recording at the time the event was captured",
            "system": True,
            "used_for_debug": True,
        },
        "$cymbal_errors": {
            "label": "Exception processing errors",
            "description": "Errors encountered while trying to process exceptions.",
            "system": True,
        },
        "$geoip_city_name": {
            "label": "City name",
            "description": "Name of the city matched to this event's IP address.",
            "examples": ["Sydney", "Chennai", "Brooklyn"],
        },
        "$geoip_country_name": {
            "label": "Country name",
            "description": "Name of the country matched to this event's IP address.",
            "examples": ["Australia", "India", "United States"],
        },
        "$geoip_country_code": {
            "label": "Country code",
            "description": "Code of the country matched to this event's IP address.",
            "examples": ["AU", "IN", "US"],
        },
        "$geoip_continent_name": {
            "label": "Continent name",
            "description": "Name of the continent matched to this event's IP address.",
            "examples": ["Oceania", "Asia", "North America"],
        },
        "$geoip_continent_code": {
            "label": "Continent code",
            "description": "Code of the continent matched to this event's IP address.",
            "examples": ["OC", "AS", "NA"],
        },
        "$geoip_postal_code": {
            "label": "Postal code",
            "description": "Approximated postal code matched to this event's IP address.",
            "examples": ["2000", "600004", "11211"],
        },
        "$geoip_postal_code_confidence": {
            "label": "Postal code identification confidence score",
            "description": "If provided by the licensed geoip database",
            "examples": ["null", "0.1"],
            "system": True,
            "ignored_in_assistant": True,
        },
        "$geoip_latitude": {
            "label": "Latitude",
            "description": "Approximated latitude matched to this event's IP address.",
            "examples": ["-33.8591", "13.1337", "40.7"],
        },
        "$geoip_longitude": {
            "label": "Longitude",
            "description": "Approximated longitude matched to this event's IP address.",
            "examples": ["151.2", "80.8008", "-73.9"],
        },
        "$geoip_time_zone": {
            "label": "Timezone",
            "description": "Timezone matched to this event's IP address.",
            "examples": ["Australia/Sydney", "Asia/Kolkata", "America/New_York"],
        },
        "$geoip_subdivision_1_name": {
            "label": "Subdivision 1 name",
            "description": "Name of the subdivision matched to this event's IP address.",
            "examples": ["New South Wales", "Tamil Nadu", "New York"],
        },
        "$geoip_subdivision_1_code": {
            "label": "Subdivision 1 code",
            "description": "Code of the subdivision matched to this event's IP address.",
            "examples": ["NSW", "TN", "NY"],
        },
        "$geoip_subdivision_2_name": {
            "label": "Subdivision 2 name",
            "description": "Name of the second subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_2_code": {
            "label": "Subdivision 2 code",
            "description": "Code of the second subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_2_confidence": {
            "label": "Subdivision 2 identification confidence score",
            "description": "If provided by the licensed geoip database",
            "examples": ["null", "0.1"],
            "ignored_in_assistant": True,
            "system": True,
        },
        "$geoip_subdivision_3_name": {
            "label": "Subdivision 3 name",
            "description": "Name of the third subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_3_code": {
            "label": "Subdivision 3 code",
            "description": "Code of the third subdivision matched to this event's IP address.",
        },
        "$geoip_disable": {
            "label": "GeoIP disabled",
            "description": "Whether to skip GeoIP processing for the event.",
        },
        "$geoip_city_confidence": {
            "label": "GeoIP detection city confidence",
            "description": "Confidence level of the city matched to this event's IP address.",
            "examples": ["0.5"],
        },
        "$geoip_country_confidence": {
            "label": "GeoIP detection country confidence",
            "description": "Confidence level of the country matched to this event's IP address.",
            "examples": ["0.5"],
        },
        "$geoip_accuracy_radius": {
            "label": "GeoIP detection accuracy radius",
            "description": "Accuracy radius of the location matched to this event's IP address (in kilometers).",
            "examples": ["50"],
        },
        "$geoip_subdivision_1_confidence": {
            "label": "GeoIP detection subdivision 1 confidence",
            "description": "Confidence level of the first subdivision matched to this event's IP address.",
            "examples": ["0.5"],
        },
        "$el_text": {
            "label": "Element text",
            "description": "The text of the element that was clicked. Only sent with Autocapture events.",
            "examples": ["Click here!"],
        },
        "$app_build": {
            "label": "App build",
            "description": "The build number for the app.",
        },
        "$app_name": {
            "label": "App name",
            "description": "The name of the app.",
        },
        "$app_namespace": {
            "label": "App namespace",
            "description": "The namespace of the app as identified in the app store.",
            "examples": ["com.posthog.app"],
        },
        "$app_version": {
            "label": "App version",
            "description": "The version of the app.",
        },
        "$device_manufacturer": {
            "label": "Device manufacturer",
            "description": "The manufacturer of the device",
            "examples": ["Apple", "Samsung"],
        },
        "$device_name": {
            "label": "Device name",
            "description": "Name of the device",
            "examples": ["iPhone 12 Pro", "Samsung Galaxy 10"],
        },
        "$is_emulator": {
            "label": "Is emulator",
            "description": "Indicates whether the app is running on an emulator or a physical device",
            "examples": ["true", "false"],
        },
        "$is_mac_catalyst_app": {
            "label": "Is Mac Catalyst app",
            "description": "Indicates whether the app is a Mac Catalyst app running on macOS",
            "examples": ["true", "false"],
        },
        "$is_ios_running_on_mac": {
            "label": "Is iOS app running on Mac",
            "description": "Indicates whether the app is an iOS app running on macOS (Apple Silicon)",
            "examples": ["true", "false"],
        },
        "$locale": {
            "label": "Locale",
            "description": "The locale of the device",
            "examples": ["en-US", "de-DE"],
        },
        "$os_name": {
            "label": "OS name",
            "description": "The Operating System name",
            "examples": ["iOS", "Android"],
        },
        "$os_version": {
            "label": "OS version",
            "description": "The Operating System version.",
            "examples": ["15.5"],
        },
        "$timezone": {
            "label": "Timezone",
            "description": "The timezone as reported by the device",
        },
        "$timezone_offset": {
            "label": "Timezone offset",
            "description": "The timezone offset, as reported by the device. Minutes difference from UTC.",
            "type": "Numeric",
        },
        "$touch_x": {
            "label": "Touch X",
            "description": "The location of a Touch event on the X axis",
        },
        "$touch_y": {
            "label": "Touch Y",
            "description": "The location of a Touch event on the Y axis",
        },
        "$plugins_succeeded": {
            "label": "Plugins succeeded",
            "description": "Plugins that successfully processed the event, e.g. edited properties (plugin method `processEvent`).",
        },
        "$groups": {
            "label": "Groups",
            "description": "Relevant groups",
        },
        "$group_0": {
            "label": "Group 1",
            "system": True,
        },
        "$group_1": {
            "label": "Group 2",
            "system": True,
        },
        "$group_2": {
            "label": "Group 3",
            "system": True,
        },
        "$group_3": {
            "label": "Group 4",
            "system": True,
        },
        "$group_4": {
            "label": "Group 5",
            "system": True,
        },
        "$group_set": {
            "label": "Group set",
            "description": "Group properties to be set",
        },
        "$group_key": {
            "label": "Group key",
            "description": "Specified group key",
        },
        "$group_type": {
            "label": "Group type",
            "description": "Specified group type",
        },
        "$window_id": {
            "label": "Window ID",
            "description": "Unique window ID for session recording disambiguation",
            "system": True,
        },
        "$session_id": {
            "label": "Session ID",
            "description": "Unique session ID for session recording disambiguation",
            "system": True,
        },
        "$plugins_failed": {
            "label": "Plugins failed",
            "description": "Plugins that failed to process the event (plugin method `processEvent`).",
        },
        "$plugins_deferred": {
            "label": "Plugins deferred",
            "description": "Plugins to which the event was handed off post-ingestion, e.g. for export (plugin method `onEvent`).",
        },
        "$$plugin_metrics": {
            "label": "Plugin metric",
            "description": "Performance metrics for a given plugin.",
        },
        "$creator_event_uuid": {
            "label": "Creator event ID",
            "description": "Unique ID for the event, which created this person.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
        "utm_source": {
            "label": "UTM source",
            "description": "UTM source tag.",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "$initial_utm_source": {
            "label": "Initial UTM source",
            "description": "UTM source tag.",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "utm_medium": {
            "label": "UTM medium",
            "description": "UTM medium tag.",
            "examples": ["Social", "Organic", "Paid", "Email"],
        },
        "utm_campaign": {
            "label": "UTM campaign",
            "description": "UTM campaign tag.",
            "examples": ["feature launch", "discount"],
        },
        "utm_name": {
            "label": "UTM name",
            "description": "UTM campaign tag, sent via Segment.",
            "examples": ["feature launch", "discount"],
        },
        "utm_content": {
            "label": "UTM content",
            "description": "UTM content tag.",
            "examples": ["bottom link", "second button"],
        },
        "utm_term": {
            "label": "UTM term",
            "description": "UTM term tag.",
            "examples": ["free goodies"],
        },
        "$performance_page_loaded": {
            "label": "Page loaded",
            "description": "The time taken until the browser's page load event in milliseconds.",
        },
        "$performance_raw": {
            "label": "Browser performance (deprecated)",
            "description": "The browser performance entries for navigation (the page), paint, and resources. That were available when the page view event fired",
            "system": True,
        },
        "$had_persisted_distinct_id": {
            "label": "$had_persisted_distinct_id",
            "description": "",
            "system": True,
        },
        "$sentry_event_id": {
            "label": "Sentry event ID",
            "description": "This is the Sentry key for an event.",
            "examples": ["byroc2ar9ee4ijqp"],
            "system": True,
        },
        "$timestamp": {
            "label": "Timestamp (deprecated)",
            "description": "Use the SQL field `timestamp` instead. This field was previously set on some client side events.",
            "examples": ["2023-05-20T15:30:00Z"],
            "system": True,
        },
        "$sent_at": {
            "label": "Sent at",
            "description": "Time the event was sent to PostHog. Used for correcting the event timestamp when the device clock is off.",
            "examples": ["2023-05-20T15:31:00Z"],
        },
        "$browser": {
            "label": "Browser",
            "description": "Name of the browser the user has used.",
            "examples": ["Chrome", "Firefox"],
        },
        "$os": {
            "label": "OS",
            "description": "The operating system of the user.",
            "examples": ["Windows", "Mac OS X"],
        },
        "$browser_language": {
            "label": "Browser language",
            "description": "Language.",
            "examples": ["en", "en-US", "cn", "pl-PL"],
        },
        "$browser_language_prefix": {
            "label": "Browser language prefix",
            "description": "Language prefix.",
            "examples": [
                "en",
                "ja",
            ],
        },
        "$current_url": {
            "label": "Current URL",
            "description": "The URL visited at the time of the event.",
            "examples": ["https://example.com/interesting-article?parameter=true"],
        },
        "$browser_version": {
            "label": "Browser version",
            "description": "The version of the browser that was used. Used in combination with Browser.",
            "examples": ["70", "79"],
        },
        "$raw_user_agent": {
            "label": "Raw user agent",
            "description": "PostHog process information like browser, OS, and device type from the user agent string. This is the raw user agent string.",
            "examples": ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"],
        },
        "$user_agent": {
            "label": "Raw user agent",
            "description": "Some SDKs (like Android) send the raw user agent as $user_agent.",
            "examples": ["Dalvik/2.1.0 (Linux; U; Android 11; Pixel 3 Build/RQ2A.210505.002)"],
        },
        "$screen_height": {
            "label": "Screen height",
            "description": "The height of the user's entire screen (in pixels).",
            "examples": ["2160", "1050"],
        },
        "$screen_width": {
            "label": "Screen width",
            "description": "The width of the user's entire screen (in pixels).",
            "examples": ["1440", "1920"],
        },
        "$screen_name": {
            "label": "Screen name",
            "description": "The name of the active screen.",
        },
        "$viewport_height": {
            "label": "Viewport height",
            "description": "The height of the user's actual browser window (in pixels).",
            "examples": ["2094", "1031"],
        },
        "$viewport_width": {
            "label": "Viewport width",
            "description": "The width of the user's actual browser window (in pixels).",
            "examples": ["1439", "1915"],
        },
        "$lib": {
            "label": "Library",
            "description": "What library was used to send the event.",
            "examples": ["web", "posthog-ios"],
        },
        "$lib_custom_api_host": {
            "label": "Library custom API host",
            "description": "The custom API host used to send the event.",
            "examples": ["https://ph.example.com"],
        },
        "$lib_version": {
            "label": "Library version",
            "description": "Version of the library used to send the event. Used in combination with Library.",
            "examples": ["1.0.3"],
        },
        "$lib_version__major": {
            "label": "Library version (major)",
            "description": "Major version of the library used to send the event.",
            "examples": [1],
        },
        "$lib_version__minor": {
            "label": "Library version (minor)",
            "description": "Minor version of the library used to send the event.",
            "examples": [0],
        },
        "$lib_version__patch": {
            "label": "Library version (patch)",
            "description": "Patch version of the library used to send the event.",
            "examples": [3],
        },
        "$referrer": {
            "label": "Referrer URL",
            "description": "URL of where the user came from.",
            "examples": ["https://google.com/search?q=posthog&rlz=1C..."],
        },
        "$referring_domain": {
            "label": "Referring domain",
            "description": "Domain of where the user came from.",
            "examples": ["google.com", "facebook.com"],
        },
        "$user_id": {
            "label": "User ID",
            "description": "This variable will be set to the distinct ID if you've called `posthog.identify('distinct id')`. If the user is anonymous, it'll be empty.",
        },
        "$ip": {
            "label": "IP address",
            "description": "IP address for this user when the event was sent.",
            "examples": ["203.0.113.0"],
        },
        "$host": {
            "label": "Host",
            "description": "The hostname of the Current URL.",
            "examples": ["example.com", "localhost:8000"],
        },
        "$pathname": {
            "label": "Path name",
            "description": "The path of the Current URL, which means everything in the url after the domain.",
            "examples": ["/pricing", "/about-us/team"],
        },
        "$search_engine": {
            "label": "Search engine",
            "description": "The search engine the user came in from (if any).",
            "examples": ["Google", "DuckDuckGo"],
        },
        "$active_feature_flags": {
            "label": "Active feature flags",
            "description": "Keys of the feature flags that were active while this event was sent.",
            "examples": ["['beta-feature']"],
        },
        "$enabled_feature_flags": {
            "label": "Enabled feature flags",
            "description": "Keys and multivariate values of the feature flags that were active while this event was sent.",
            "examples": ['{"flag": "value"}'],
        },
        "$feature_flag_response": {
            "label": "Feature flag response",
            "description": "What the call to feature flag responded with.",
            "examples": ["true", "false"],
        },
        "$feature_flag_payload": {
            "label": "Feature flag response payload",
            "description": "The JSON payload that the call to feature flag responded with (if any)",
            "examples": ['{"variant": "test"}'],
        },
        "$feature_flag": {
            "label": "Feature flag",
            "description": 'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag_called event. If you want to filter other events, try "Active feature flags".',
            "examples": ["beta-feature"],
        },
        "$feature_flag_reason": {
            "label": "Feature flag evaluation reason",
            "description": "The reason the feature flag was matched or not matched.",
            "examples": ["Matched condition set 1"],
        },
        "$feature_flag_request_id": {
            "label": "Feature flag request ID",
            "description": "The unique identifier for the request that retrieved this feature flag result.\n\nNote: Primarily used by PostHog support for debugging issues with feature flags.",
            "examples": ["01234567-89ab-cdef-0123-456789abcdef"],
        },
        "$feature_flag_version": {
            "label": "Feature flag version",
            "description": "The version of the feature flag that was called.",
            "examples": ["3"],
        },
        "$survey_response": {
            "label": "Survey response",
            "description": "The response value for the first question in the survey.",
            "examples": ["I love it!", 5, "['choice 1', 'choice 3']"],
        },
        "$survey_name": {
            "label": "Survey name",
            "description": "The name of the survey.",
            "examples": ["Product Feedback for New Product", "Home page NPS"],
        },
        "$survey_questions": {
            "label": "Survey questions",
            "description": "The questions asked in the survey.",
        },
        "$survey_id": {
            "label": "Survey ID",
            "description": "The unique identifier for the survey.",
        },
        "$survey_iteration": {
            "label": "Survey iteration number",
            "description": "The iteration number for the survey.",
        },
        "$survey_iteration_start_date": {
            "label": "Survey iteration start date",
            "description": "The start date for the current iteration of the survey.",
        },
        "$survey_submission_id": {
            "description": "The unique identifier for the survey submission. Relevant for partial submissions, as they submit multiple 'survey sent' events. This is what allows us to count them as a single submission.",
            "label": "Survey submission ID",
        },
        "$survey_completed": {
            "description": "If a survey was fully completed (all questions answered), this will be true.",
            "label": "Survey completed",
        },
        "$survey_partially_completed": {
            "description": "If a survey was partially completed (some questions answered) on dismissal, this will be true.",
            "label": "Survey partially completed",
        },
        "$device": {
            "label": "Device",
            "description": "The mobile device that was used.",
            "examples": ["iPad", "iPhone", "Android"],
        },
        "$sentry_url": {
            "label": "Sentry URL",
            "description": "Direct link to the exception in Sentry",
            "examples": ["https://sentry.io/..."],
        },
        "$device_type": {
            "label": "Device type",
            "description": "The type of device that was used.",
            "examples": ["Mobile", "Tablet", "Desktop"],
        },
        "$screen_density": {
            "label": "Screen density",
            "description": 'The logical density of the display. This is a scaling factor for the Density Independent Pixel unit, where one DIP is one pixel on an approximately 160 dpi screen (for example a 240x320, 1.5"x2" screen), providing the baseline of the system\'s display. Thus on a 160dpi screen this density value will be 1; on a 120 dpi screen it would be .75; etc.',
            "examples": [2.75],
        },
        "$device_model": {
            "label": "Device model",
            "description": "The model of the device that was used.",
            "examples": ["iPhone9,3", "SM-G965W"],
        },
        "$network_wifi": {
            "label": "Network WiFi",
            "description": "Whether the user was on WiFi when the event was sent.",
            "examples": ["true", "false"],
        },
        "$network_bluetooth": {
            "label": "Network Bluetooth",
            "description": "Whether the user was on Bluetooth when the event was sent.",
            "examples": ["true", "false"],
        },
        "$network_cellular": {
            "label": "Network Cellular",
            "description": "Whether the user was on cellular when the event was sent.",
            "examples": ["true", "false"],
        },
        "$client_session_initial_referring_host": {
            "label": "Referrer host",
            "description": "Host that the user came from. (First-touch, session-scoped)",
            "examples": ["google.com", "facebook.com"],
        },
        "$client_session_initial_pathname": {
            "label": "Initial path",
            "description": "Path that the user started their session on. (First-touch, session-scoped)",
            "examples": ["/register", "/some/landing/page"],
        },
        "$client_session_initial_utm_source": {
            "label": "Initial UTM source",
            "description": "UTM Source. (First-touch, session-scoped)",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "$client_session_initial_utm_campaign": {
            "label": "Initial UTM campaign",
            "description": "UTM Campaign. (First-touch, session-scoped)",
            "examples": ["feature launch", "discount"],
        },
        "$client_session_initial_utm_medium": {
            "label": "Initial UTM medium",
            "description": "UTM Medium. (First-touch, session-scoped)",
            "examples": ["Social", "Organic", "Paid", "Email"],
        },
        "$client_session_initial_utm_content": {
            "label": "Initial UTM source",
            "description": "UTM Source. (First-touch, session-scoped)",
            "examples": ["bottom link", "second button"],
        },
        "$client_session_initial_utm_term": {
            "label": "Initial UTM term",
            "description": "UTM term. (First-touch, session-scoped)",
            "examples": ["free goodies"],
        },
        "$network_carrier": {
            "label": "Network carrier",
            "description": "The network carrier that the user is on.",
            "examples": ["cricket", "telecom"],
        },
        "from_background": {
            "label": "From background",
            "description": "Whether the app was opened for the first time or from the background.",
            "examples": ["true", "false"],
        },
        "url": {
            "label": "URL",
            "description": "The deep link URL that the app was opened from.",
            "examples": ["https://open.my.app"],
        },
        "referring_application": {
            "label": "Referrer application",
            "description": "The namespace of the app that made the request.",
            "examples": ["com.posthog.app"],
        },
        "version": {
            "label": "App version",
            "description": "The version of the app",
            "examples": ["1.0.0"],
        },
        "previous_version": {
            "label": "App previous version",
            "description": "The previous version of the app",
            "examples": ["1.0.0"],
        },
        "build": {
            "label": "App build",
            "description": "The build number for the app",
            "examples": ["1"],
        },
        "previous_build": {
            "label": "App previous build",
            "description": "The previous build number for the app",
            "examples": ["1"],
        },
        "gclid": {
            "label": "gclid",
            "description": "Google Click ID",
        },
        "rdt_cid": {
            "label": "rdt_cid",
            "description": "Reddit Click ID",
        },
        "epik": {
            "label": "epik",
            "description": "Pinterest Click ID",
        },
        "qclid": {
            "label": "qclid",
            "description": "Quora Click ID",
        },
        "sccid": {
            "label": "sccid",
            "description": "Snapchat Click ID",
        },
        "irclid": {
            "label": "irclid",
            "description": "Impact Click ID",
        },
        "_kx": {
            "label": "_kx",
            "description": "Klaviyo Tracking ID",
        },
        "gad_source": {
            "label": "gad_source",
            "description": "Google Ads Source",
        },
        "gclsrc": {
            "label": "gclsrc",
            "description": "Google Click Source",
        },
        "dclid": {
            "label": "dclid",
            "description": "DoubleClick ID",
        },
        "gbraid": {
            "label": "gbraid",
            "description": "Google Ads, web to app",
        },
        "wbraid": {
            "label": "wbraid",
            "description": "Google Ads, app to web",
        },
        "fbclid": {
            "label": "fbclid",
            "description": "Facebook Click ID",
        },
        "msclkid": {
            "label": "msclkid",
            "description": "Microsoft Click ID",
        },
        "twclid": {
            "label": "twclid",
            "description": "Twitter Click ID",
        },
        "li_fat_id": {
            "label": "li_fat_id",
            "description": "LinkedIn First-Party Ad Tracking ID",
        },
        "mc_cid": {
            "label": "mc_cid",
            "description": "Mailchimp Campaign ID",
        },
        "igshid": {
            "label": "igshid",
            "description": "Instagram Share ID",
        },
        "ttclid": {
            "label": "ttclid",
            "description": "TikTok Click ID",
        },
        "$is_identified": {
            "label": "Is identified",
            "description": "Client-side property set by posthog-js indicating whether the user has been previously identified on the device.",
        },
        "$initial_person_info": {
            "label": "Initial person info",
            "description": "posthog-js initial person information. used in the $set_once flow",
            "system": True,
        },
        "revenue": {
            "label": "Revenue",
            "description": "The revenue associated with the event. By default, this is in USD, but the currency property can be used to specify a different currency.",
            "examples": [10.0],
        },
        "currency": {
            "label": "Currency",
            "description": "The currency code associated with the event.",
            "examples": ["USD", "EUR", "GBP", "CAD"],
        },
        "$web_vitals_enabled_server_side": {
            "label": "Web vitals enabled server side",
            "description": "Whether web vitals was enabled in remote config",
        },
        "$web_vitals_FCP_event": {
            "label": "Web vitals FCP measure event details",
        },
        "$web_vitals_FCP_value": {
            "label": "Web vitals FCP value",
        },
        "$web_vitals_LCP_event": {
            "label": "Web vitals LCP measure event details",
        },
        "$web_vitals_LCP_value": {
            "label": "Web vitals LCP value",
        },
        "$web_vitals_INP_event": {
            "label": "Web vitals INP measure event details",
        },
        "$web_vitals_INP_value": {
            "label": "Web vitals INP value",
        },
        "$web_vitals_CLS_event": {
            "label": "Web vitals CLS measure event details",
        },
        "$web_vitals_CLS_value": {
            "label": "Web vitals CLS value",
        },
        "$web_vitals_allowed_metrics": {
            "label": "Web vitals allowed metrics",
            "description": "Allowed web vitals metrics config.",
            "examples": ['["LCP", "CLS"]'],
            "system": True,
        },
        "$prev_pageview_last_scroll": {
            "label": "Previous pageview last scroll",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "examples": [0],
        },
        "$prev_pageview_id": {
            "label": "Previous pageview ID",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "examples": ["1"],
            "system": True,
        },
        "$prev_pageview_last_scroll_percentage": {
            "label": "Previous pageview last scroll percentage",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "examples": [0],
        },
        "$prev_pageview_max_scroll": {
            "examples": [0],
            "label": "Previous pageview max scroll",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
        },
        "$prev_pageview_max_scroll_percentage": {
            "examples": [0],
            "label": "Previous pageview max scroll percentage",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
        },
        "$prev_pageview_last_content": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview last content",
        },
        "$prev_pageview_last_content_percentage": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview last content percentage",
        },
        "$prev_pageview_max_content": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview max content",
        },
        "$prev_pageview_max_content_percentage": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview max content percentage",
        },
        "$prev_pageview_pathname": {
            "examples": ["/pricing", "/about-us/team"],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview pathname",
        },
        "$prev_pageview_duration": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview duration",
        },
        "$surveys_activated": {
            "label": "Surveys activated",
            "description": "The surveys that were activated for this event.",
        },
        "$process_person_profile": {
            "label": "Person profile processing flag",
            "description": "The setting from an SDK to control whether an event has person processing enabled",
            "system": True,
        },
        "$dead_clicks_enabled_server_side": {
            "label": "Dead clicks enabled server side",
            "description": "Whether dead clicks were enabled in remote config",
            "system": True,
        },
        "$dead_click_scroll_delay_ms": {
            "label": "Dead click scroll delay in milliseconds",
            "description": "The delay between a click and the next scroll event",
            "system": True,
        },
        "$dead_click_mutation_delay_ms": {
            "label": "Dead click mutation delay in milliseconds",
            "description": "The delay between a click and the next mutation event",
            "system": True,
        },
        "$dead_click_absolute_delay_ms": {
            "label": "Dead click absolute delay in milliseconds",
            "description": "The delay between a click and having seen no activity at all",
            "system": True,
        },
        "$dead_click_selection_changed_delay_ms": {
            "label": "Dead click selection changed delay in milliseconds",
            "description": "The delay between a click and the next text selection change event",
            "system": True,
        },
        "$dead_click_last_mutation_timestamp": {
            "label": "Dead click last mutation timestamp",
            "description": "debug signal time of the last mutation seen by dead click autocapture",
            "system": True,
        },
        "$dead_click_event_timestamp": {
            "label": "Dead click event timestamp",
            "description": "debug signal time of the event that triggered dead click autocapture",
            "system": True,
        },
        "$dead_click_scroll_timeout": {
            "label": "Dead click scroll timeout",
            "description": "whether the dead click autocapture passed the threshold for waiting for a scroll event",
        },
        "$dead_click_mutation_timeout": {
            "label": "Dead click mutation timeout",
            "description": "whether the dead click autocapture passed the threshold for waiting for a mutation event",
            "system": True,
        },
        "$dead_click_absolute_timeout": {
            "label": "Dead click absolute timeout",
            "description": "whether the dead click autocapture passed the threshold for waiting for any activity",
            "system": True,
        },
        "$dead_click_selection_changed_timeout": {
            "label": "Dead click selection changed timeout",
            "description": "whether the dead click autocapture passed the threshold for waiting for a text selection change event",
            "system": True,
        },
        # AI
        "$ai_base_url": {
            "label": "AI base URL (LLM)",
            "description": "The base URL of the request made to the LLM API.",
            "examples": ["https://api.openai.com/v1/"],
        },
        "$ai_http_status": {
            "label": "AI HTTP status (LLM)",
            "description": "The HTTP status code of the request made to the LLM API.",
            "examples": [200, 429],
        },
        "$ai_input": {
            "label": "AI input (LLM)",
            "description": "The input JSON that was sent to the LLM API.",
            "examples": ['{"content": "Explain quantum computing in simple terms.", "role": "user"}'],
        },
        "$ai_input_tokens": {
            "label": "AI input tokens (LLM)",
            "description": "The number of tokens in the input prompt that was sent to the LLM API.",
            "examples": [23],
        },
        "$ai_output_choices": {
            "label": "AI output (LLM)",
            "description": "The output message choices JSON that was received from the LLM API.",
            "examples": [
                '{"choices": [{"text": "Quantum computing is a type of computing that harnesses the power of quantum mechanics to perform operations on data."}]}',
            ],
        },
        "$ai_output_tokens": {
            "label": "AI output tokens (LLM)",
            "description": "The number of tokens in the output from the LLM API.",
            "examples": [23],
        },
        "$ai_cache_read_input_tokens": {
            "label": "AI cache read input tokens (LLM)",
            "description": "The number of tokens read from the cache for the input prompt.",
            "examples": [23],
        },
        "$ai_cache_creation_input_tokens": {
            "label": "AI cache creation input tokens (LLM)",
            "description": "The number of tokens created in the cache for the input prompt (anthropic only).",
            "examples": [23],
        },
        "$ai_reasoning_tokens": {
            "label": "AI reasoning tokens (LLM)",
            "description": "The number of tokens in the reasoning output from the LLM API.",
            "examples": [23],
        },
        "$ai_input_cost_usd": {
            "label": "AI input cost USD (LLM)",
            "description": "The cost in USD of the input tokens sent to the LLM API.",
            "examples": [0.0017],
        },
        "$ai_output_cost_usd": {
            "label": "AI output cost USD (LLM)",
            "description": "The cost in USD of the output tokens received from the LLM API.",
            "examples": [0.0024],
        },
        "$ai_total_cost_usd": {
            "label": "AI total cost USD (LLM)",
            "description": "The total cost in USD of the request made to the LLM API (input + output costs).",
            "examples": [0.0041],
        },
        "$ai_latency": {
            "label": "AI latency (LLM)",
            "description": "The latency of the request made to the LLM API, in seconds.",
            "examples": [0.361],
        },
        "$ai_model": {
            "label": "AI model (LLM)",
            "description": "The model used to generate the output from the LLM API.",
            "examples": ["gpt-4o-mini"],
        },
        "$ai_model_parameters": {
            "label": "AI model parameters (LLM)",
            "description": "The parameters used to configure the model in the LLM API, in JSON.",
            "examples": ['{"temperature": 0.5, "max_tokens": 50}'],
        },
        "$ai_tools": {
            "label": "AI tools (LLM)",
            "description": "The tools available to the LLM.",
            "examples": [
                '[{"type": "function", "function": {"name": "tool1", "arguments": {"arg1": "value1", "arg2": "value2"}}}]',
            ],
        },
        "$ai_stream": {
            "label": "AI stream (LLM)",
            "description": "Whether the response from the LLM API was streamed.",
            "examples": ["true", "false"],
        },
        "$ai_temperature": {
            "label": "AI temperature (LLM)",
            "description": "The temperature parameter used in the request to the LLM API.",
            "examples": [0.7, 1.0],
        },
        "$ai_input_state": {
            "label": "AI Input State (LLM)",
            "description": "Input state of the LLM agent.",
        },
        "$ai_output_state": {
            "label": "AI Output State (LLM)",
            "description": "Output state of the LLM agent.",
        },
        "$ai_provider": {
            "label": "AI Provider (LLM)",
            "description": "The provider of the AI model used to generate the output from the LLM API.",
            "examples": ["openai"],
        },
        "$ai_trace_id": {
            "label": "AI Trace ID (LLM)",
            "description": "The trace ID of the request made to the LLM API. Used to group together multiple generations into a single trace.",
            "examples": ["c9222e05-8708-41b8-98ea-d4a21849e761"],
        },
        "$ai_session_id": {
            "label": "AI Session ID (LLM)",
            "description": "Groups related traces together in a session (e.g., a conversation or workflow). One session can contain many traces.",
            "examples": ["session-abc-123", "conv-user-456"],
        },
        "$ai_request_url": {
            "label": "AI Request URL (LLM)",
            "description": "The full URL of the request made to the LLM API.",
            "examples": ["https://api.openai.com/v1/chat/completions"],
        },
        "$ai_evaluation_id": {
            "label": "AI Evaluation ID (LLM)",
            "description": "The unique identifier of the evaluation configuration used to judge the AI event.",
            "examples": ["550e8400-e29b-41d4-a716-446655440000"],
        },
        "$ai_evaluation_name": {
            "label": "AI Evaluation Name (LLM)",
            "description": "The name of the evaluation configuration used.",
            "examples": ["Factual accuracy check", "Response relevance"],
        },
        "$ai_evaluation_model": {
            "label": "AI Evaluation Model (LLM)",
            "description": "The LLM model used as the judge for the evaluation.",
            "examples": ["gpt-4", "claude-3-opus"],
        },
        "$ai_evaluation_start_time": {
            "label": "AI Evaluation Start Time (LLM)",
            "description": "The timestamp when the evaluation started executing.",
            "examples": ["2025-01-15T10:30:00Z"],
        },
        "$ai_evaluation_result": {
            "label": "AI Evaluation Result (LLM)",
            "description": "The boolean verdict of the evaluation (true = pass, false = fail).",
            "examples": [True, False],
        },
        "$ai_evaluation_reasoning": {
            "label": "AI Evaluation Reasoning (LLM)",
            "description": "The LLM's explanation for why the evaluation passed or failed.",
            "examples": ["The response accurately addresses the query", "The output contains factual inaccuracies"],
        },
        "$ai_target_event_id": {
            "label": "AI Target Event ID (LLM)",
            "description": "The unique identifier of the event being evaluated.",
            "examples": ["c9222e05-8708-41b8-98ea-d4a21849e761"],
        },
        "$ai_target_event_type": {
            "label": "AI Target Event Type (LLM)",
            "description": "The type of event being evaluated (e.g., $ai_generation).",
            "examples": ["$ai_generation", "$ai_span"],
        },
        "$ai_metric_name": {
            "label": "AI Metric Name (LLM)",
            "description": "The name assigned to the metric used to evaluate the LLM trace.",
            "examples": ["rating", "accuracy"],
        },
        "$ai_metric_value": {
            "label": "AI Metric Value (LLM)",
            "description": "The value assigned to the metric used to evaluate the LLM trace.",
            "examples": ["negative", "95"],
        },
        "$ai_feedback_text": {
            "label": "AI Feedback Text (LLM)",
            "description": "The text provided by the user for feedback on the LLM trace.",
            "examples": ['"The response was helpful, but it did not use the provided context."'],
        },
        "$ai_parent_id": {
            "label": "AI Parent ID (LLM)",
            "description": "The parent span ID of a span or generation, used to group a trace into a tree view.",
            "examples": ["bdf42359-9364-4db7-8958-c001f28c9255"],
        },
        "$ai_span_id": {
            "label": "AI Span ID (LLM)",
            "description": "The unique identifier for a LLM trace, generation, or span.",
            "examples": ["bdf42359-9364-4db7-8958-c001f28c9255"],
        },
        "$ai_span_name": {
            "label": "AI Span Name (LLM)",
            "description": "The name given to this LLM trace, generation, or span.",
            "examples": ["summarize_text"],
        },
        "$csp_document_url": {
            "label": "Document URL",
            "description": "The URL of the document where the violation occurred.",
            "examples": ["https://example.com/page"],
        },
        "$csp_violated_directive": {
            "label": "Violated directive",
            "description": "The CSP directive that was violated.",
            "examples": ["script-src", "img-src", "default-src"],
        },
        "$csp_effective_directive": {
            "label": "Effective directive",
            "description": "The CSP directive that was effectively violated.",
            "examples": ["script-src", "img-src", "default-src"],
        },
        "$csp_original_policy": {
            "label": "Original policy",
            "description": "The CSP policy that was active when the violation occurred.",
            "examples": ["default-src 'self'; script-src 'self' example.com"],
        },
        "$csp_disposition": {
            "label": "Disposition",
            "description": "The disposition of the CSP policy that was violated (enforce or report).",
            "examples": ["enforce", "report"],
        },
        "$csp_blocked_url": {
            "label": "Blocked URL",
            "description": "The URL that was blocked by the CSP policy.",
            "examples": ["https://malicious-site.com/script.js"],
        },
        "$csp_line_number": {
            "label": "Line number",
            "description": "The line number in the source file where the violation occurred.",
            "examples": ["42"],
        },
        "$csp_column_number": {
            "label": "Column number",
            "description": "The column number in the source file where the violation occurred.",
            "examples": ["13"],
        },
        "$csp_source_file": {
            "label": "Source file",
            "description": "The source file where the violation occurred.",
            "examples": ["script.js"],
        },
        "$csp_status_code": {
            "label": "Status code",
            "description": "The HTTP status code that was returned when trying to load the blocked resource.",
            "examples": ["200", "404"],
        },
        "$csp_script_sample": {
            "label": "Script sample",
            "description": "An escaped sample of the script that caused the violation. Usually capped at 40 characters.",
            "examples": ["eval('alert(1)')"],
        },
        "$csp_report_type": {
            "label": "Report type",
            "description": "The type of CSP report.",
        },
        "$csp_raw_report": {
            "label": "Raw CSP report",
            "description": "The raw CSP report as received from the browser.",
        },
        "$csp_referrer": {
            "label": "CSP Referrer",
            "description": "The referrer of the CSP report if available.",
            "examples": ["https://example.com/referrer"],
        },
        "$csp_version": {
            "label": "CSP Policy version",
            "description": "The version of the CSP policy. Must be provided in the report URL.",
            "examples": ["1.0"],
        },
    },
    "numerical_event_properties": {},
    "person_properties": {
        "email": {
            "label": "Email address",
            "description": "The email address of the user.",
            "examples": ["johnny.appleseed@icloud.com", "sales@posthog.com", "test@example.com"],
            "type": "String",
        },
        "$virt_initial_channel_type": {
            "description": "What type of acquisition channel this user initially came from. Learn more about channels types and how to customise them in [our documentation](https://posthog.com/docs/data/channel-type)",
            "examples": ["Paid Search", "Organic Video", "Direct"],
            "label": "Initial channel type",
            "type": "String",
            "virtual": True,
        },
        "$virt_initial_referring_domain_type": {
            "description": "What type of referring domain this user initially came from.",
            "examples": ["Search", "Video", "Direct"],
            "label": "Initial referring domain type",
            "type": "String",
            "virtual": True,
        },
        "$virt_revenue": {
            "description": "The total revenue for this person. This will always be the current total revenue even when referring to a person via events.",
            "label": "Total revenue",
            "type": "Numeric",
            "virtual": True,
        },
        "$virt_revenue_last_30_days": {
            "description": "The total revenue for this person in the last 30 days.",
            "label": "Total revenue in the last 30 days",
            "type": "Numeric",
            "virtual": True,
        },
    },
    "session_properties": {
        "$session_duration": {
            "label": "Session duration",
            "description": "The duration of the session being tracked. Learn more about how PostHog tracks sessions in [our documentation](https://posthog.com/docs/user-guides/sessions).\n\nNote: If the duration is formatted as a single number (not `HH:MM:SS`), it's in seconds.",
            "examples": ["30", "146", "2"],
            "type": "Numeric",
        },
        "$start_timestamp": {
            "label": "Start timestamp",
            "description": "The timestamp of the first event from this session.",
            "examples": ["2023-05-20T15:30:00Z"],
            "type": "DateTime",
        },
        "$end_timestamp": {
            "label": "End timestamp",
            "description": "The timestamp of the last event from this session.",
            "examples": ["2023-05-20T16:30:00Z"],
            "type": "DateTime",
        },
        "$entry_current_url": {
            "label": "Entry URL",
            "description": "The first URL visited in this session.",
            "examples": ["https://example.com/interesting-article?parameter=true"],
            "type": "String",
        },
        "$entry_pathname": {
            "label": "Entry pathname",
            "description": "The first pathname visited in this session.",
            "examples": ["/interesting-article?parameter=true"],
            "type": "String",
        },
        "$end_current_url": {
            "label": "End URL",
            "description": "The last URL visited in this session.",
            "examples": ["https://example.com/interesting-article?parameter=true"],
            "type": "String",
        },
        "$end_pathname": {
            "label": "End pathname",
            "description": "The last pathname visited in this session.",
            "examples": ["/interesting-article?parameter=true"],
            "type": "String",
        },
        "$exit_current_url": {
            "label": "Exit URL",
            "description": "The last URL visited in this session. (deprecated, use $end_current_url).",
            "examples": ["https://example.com/interesting-article?parameter=true"],
            "type": "String",
        },
        "$exit_pathname": {
            "label": "Exit pathname",
            "description": "The last pathname visited in this session. (deprecated, use $end_pathname).",
            "examples": ["/interesting-article?parameter=true"],
            "type": "String",
        },
        "$pageview_count": {
            "label": "Pageview count",
            "description": "The number of page view events in this session.",
            "examples": ["123"],
            "type": "Numeric",
        },
        "$autocapture_count": {
            "label": "Autocapture count",
            "description": "The number of autocapture events in this session.",
            "examples": ["123"],
            "type": "Numeric",
        },
        "$screen_count": {
            "label": "Screen count",
            "description": "The number of screen events in this session.",
            "examples": ["123"],
            "type": "Numeric",
        },
        "$channel_type": {
            "label": "Channel type",
            "description": "What type of acquisition channel this traffic came from.",
            "examples": ["Paid Search", "Organic Video", "Direct"],
            "type": "String",
        },
        "$is_bounce": {
            "label": "Is bounce",
            "description": "Whether the session was a bounce.",
            "examples": ["true", "false"],
            "type": "Boolean",
        },
        "$last_external_click_url": {
            "label": "Last external click URL",
            "description": "The last external URL clicked in this session.",
            "examples": ["https://example.com/interesting-article?parameter=true"],
        },
        "$vitals_lcp": {
            "label": "Web vitals LCP",
            "description": "The time it took for the Largest Contentful Paint on the page. This captures the perceived load time of the page, and measure how long it took for the main content of the page to be visible to users.",
            "examples": ["2.2"],
        },
    },
    "groups": {
        "$group_key": {
            "label": "Group key",
            "description": "Specified group key",
        },
        "$virt_revenue": {
            "description": "The total revenue for this group. This will always be the current total revenue even when referring to a group via events.",
            "label": "Total revenue",
            "type": "Numeric",
            "virtual": True,
        },
        "$virt_revenue_last_30_days": {
            "description": "The total revenue for this group in the last 30 days.",
            "label": "Total revenue in the last 30 days",
            "type": "Numeric",
            "virtual": True,
        },
    },
    "replay": {
        "snapshot_source": {
            "label": "Platform",
            "description": "Platform the session was recorded on",
            "examples": ["web", "mobile"],
        },
        "console_log_level": {
            "label": "Log level",
            "description": "Level of console logs captured",
            "examples": ["info", "warn", "error"],
        },
        "console_log_query": {
            "label": "Console log",
            "description": "Text of console logs captured",
        },
        "visited_page": {
            "label": "Visited page",
            "description": "URL a user visited during their session",
        },
        "comment_text": {
            "label": "Comment text",
            "description": "Search for text within comments on the recording",
        },
        "click_count": {
            "label": "Clicks",
            "description": "Number of clicks during the session",
        },
        "keypress_count": {
            "label": "Key presses",
            "description": "Number of key presses during the session",
        },
        "console_error_count": {
            "label": "Errors",
            "description": "Number of console errors during the session",
        },
    },
    "log_entries": {
        "level": {
            "label": "Console log level",
            "description": "Level of the ",
            "examples": ["info", "warn", "error"],
        },
        "message": {
            "label": "Console log message",
            "description": "The contents of the log message",
        },
    },
    "error_tracking_issues": {
        "assignee": {"label": "Issue assignee", "description": "The current assignee of an issue."},
        "name": {"label": "Issue name", "description": "The name of an issue."},
        "issue_description": {"label": "Issue description", "description": "The description of an issue."},
        "first_seen": {
            "label": "Issue first seen",
            "description": "The first time the issue was seen.",
            "type": "DateTime",
        },
    },
    # The prefix on the keys should match DatabaseSchemaManagedViewTableKind
    "revenue_analytics_properties": {
        "source_label": {
            "label": "Source",
            "description": "The source of the revenue event - either an event or a Data Warehouse integration.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.id": {
            "label": "Customer ID",
            "description": "The ID of the customer connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.name": {
            "label": "Customer Name",
            "description": "The name of the customer connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.email": {
            "label": "Customer Email",
            "description": "The email of the customer connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.phone": {
            "label": "Customer Phone",
            "description": "The phone of the customer connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.address": {
            "label": "Customer Address",
            "description": "The address of the customer connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.country": {
            "label": "Customer Country",
            "description": "The country of the customer connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.cohort": {
            "label": "Customer Cohort",
            "description": "The cohort of the customer connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.initial_coupon": {
            "label": "Customer Initial Coupon",
            "description": "The name of the coupon on the initial revenue event for the customer.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_customer.initial_coupon_id": {
            "label": "Customer Initial Coupon ID",
            "description": "The ID of the coupon on the initial revenue event for the customer.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_product.name": {
            "label": "Product Name",
            "description": "The name of the product connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_invoice_item.amount": {
            "label": "Amount",
            "description": "The amount of the revenue event.",
            "type": "Numeric",
            "virtual": True,
        },
        "revenue_analytics_invoice_item.timestamp": {
            "label": "Timestamp",
            "description": "When the revenue event was executed.",
            "type": "DateTime",
            "virtual": True,
        },
        "revenue_analytics_invoice_item.created_at": {
            "label": "Created At",
            "description": "When the revenue event was created.",
            "type": "DateTime",
            "virtual": True,
        },
        "revenue_analytics_invoice_item.coupon": {
            "label": "Coupon",
            "description": "The name of the coupon connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_invoice_item.coupon_id": {
            "label": "Coupon ID",
            "description": "The ID of the coupon connected to the revenue event.",
            "type": "String",
            "virtual": True,
        },
        "revenue_analytics_subscription.started_at": {
            "label": "Subscription Started At",
            "description": "The started at date of the subscription connected to the revenue event.",
            "type": "DateTime",
            "virtual": True,
        },
        "revenue_analytics_subscription.ended_at": {
            "label": "Subscription Ended At",
            "description": "The ended at date of the subscription connected to the revenue event.",
            "type": "DateTime",
            "virtual": True,
        },
    },
}

# copy distinct_id to event properties (needs to be done before copying to person properties, so it exists in person properties as well)
CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"]["distinct_id"] = CORE_FILTER_DEFINITIONS_BY_GROUP["metadata"][
    "distinct_id"
]

# copy meta properties to event_metadata
CORE_FILTER_DEFINITIONS_BY_GROUP["event_metadata"] = {}
for key in ["distinct_id", "timestamp", "event", "person_id", "person_mode"]:
    CORE_FILTER_DEFINITIONS_BY_GROUP["event_metadata"][key] = CORE_FILTER_DEFINITIONS_BY_GROUP["metadata"][key]


def decapitalize_first_word(text: str) -> str:
    """Decapitalize the first word of a string, but leave acronyms and exceptions like `GeoIP` intact."""

    def decapitalize(match):
        """Decapitalize words like `Browser`, but leaves acronyms like `UTM` and exceptions like `GeoIP` intact."""
        word = match.group(0)
        return word[0].lower() + word[1:] if word.islower() or (not word.isupper() and word != "GeoIP") else word

    return re.sub(r"^\b\w+\b", decapitalize, text, count=1)


for key, value in CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"].items():
    if key in PERSON_PROPERTIES_ADAPTED_FROM_EVENT or key.startswith("$geoip_"):
        CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"][key] = {
            **value,
            "label": f"Latest {decapitalize_first_word(value['label'])}",
            "description": (
                f"{value['description']} Data from the last time this user was seen."
                if "description" in value
                else "Data from the last time this user was seen."
            ),
        }

        CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"][f"$initial_{key.lstrip('$')}"] = {
            **value,
            "label": f"Initial {decapitalize_first_word(value['label'])}",
            "description": (
                f"{value['description']} Data from the first time this user was seen."
                if "description" in value
                else "Data from the first time this user was seen."
            ),
        }
    else:
        CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"][key] = value

    if key in SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS:
        CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][f"$entry_{key.lstrip('$')}"] = {
            **value,
            "label": f"Entry {decapitalize_first_word(value['label'])}",
            "description": (
                f"{value['description']} Data from the first event in this session."
                if "description" in value
                else "Data from the first event in this session."
            ),
        }

for key in SESSION_PROPERTIES_ALSO_INCLUDED_IN_EVENTS:
    mapped_key = key.lstrip("$") if key != "$current_url" else "url"

    CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"][f"$session_entry_{mapped_key}"] = {
        **CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"][key],
        "label": f"Session entry {CORE_FILTER_DEFINITIONS_BY_GROUP['event_properties'][key]['label']}",
        "description": (
            f"{CORE_FILTER_DEFINITIONS_BY_GROUP['event_properties'][key]['description']} Captured at the start of the session and remains constant for the duration of the session."
        ),
        "ignored_in_assistant": True,
    }


PROPERTY_NAME_ALIASES = {
    key: value["label"]
    for key, value in CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"].items()
    if "label" in value and "deprecated" not in value["label"]
}
