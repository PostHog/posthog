hardcoded_prop_defs: dict = {
    "events": {
        "": {
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
        },
        "$autocapture": {
            "label": "Autocapture",
            "description": "User interactions that were automatically captured.",
            "examples": ["clicked button"],
        },
        "$copy_autocapture": {
            "label": "Clipboard autocapture",
            "description": "Selected text automatically captured when a user copies or cuts.",
        },
        "$screen": {
            "label": "Screen",
            "description": "When a user loads a screen in a mobile app.",
        },
        "$set": {
            "label": "Set",
            "description": "Setting person properties.",
        },
        "$opt_in": {
            "label": "Opt In",
            "description": "When a user opts into analytics.",
        },
        "$feature_flag_called": {
            "label": "Feature Flag Called",
            "description": (
                'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag event. If you want to filter other events, try "Active Feature Flags".'
            ),
            "examples": ["beta-feature"],
        },
        "$feature_view": {
            "label": "Feature View",
            "description": "When a user views a feature.",
        },
        "$feature_interaction": {
            "label": "Feature Interaction",
            "description": "When a user interacts with a feature.",
        },
        "$capture_metrics": {
            "label": "Capture Metrics",
            "description": "Metrics captured with values pertaining to your systems at a specific point in time",
        },
        "$identify": {
            "label": "Identify",
            "description": "A user has been identified with properties",
        },
        "$create_alias": {
            "label": "Alias",
            "description": "An alias ID has been added to a user",
        },
        "$merge_dangerously": {
            "label": "Merge",
            "description": "An alias ID has been added to a user",
        },
        "$groupidentify": {
            "label": "Group Identify",
            "description": "A group has been identified with properties",
        },
        "$rageclick": {
            "label": "Rageclick",
            "description": "A user has rapidly and repeatedly clicked in a single place",
        },
        "$exception": {
            "label": "Exception",
            "description": "Automatically captured exceptions from the client Sentry integration",
        },
        "$web_vitals": {
            "label": "Web vitals",
            "description": "Automatically captured web vitals data",
        },
        "Application Opened": {
            "label": "Application Opened",
            "description": "When a user opens the app either for the first time or from the foreground.",
        },
        "Application Backgrounded": {
            "label": "Application Backgrounded",
            "description": "When a user puts the app in the background.",
        },
        "Application Updated": {
            "label": "Application Updated",
            "description": "When a user upgrades the app.",
        },
        "Application Installed": {
            "label": "Application Installed",
            "description": "When a user installs the app.",
        },
        "Application Became Active": {
            "label": "Application Became Active",
            "description": "When a user puts the app in the foreground.",
        },
        "Deep Link Opened": {
            "label": "Deep Link Opened",
            "description": "When a user opens the app via a deep link.",
        },
    },
    "elements": {
        "tag_name": {
            "label": "Tag Name",
            "description": "HTML tag name of the element which you want to filter.",
            "examples": ["a", "button", "input"],
        },
        "selector": {
            "label": "CSS Selector",
            "description": "Select any element by CSS selector.",
            "examples": ["div > a", "table td:nth-child(2)", ".my-class"],
        },
        "text": {
            "label": "Text",
            "description": "Filter on the inner text of the HTML element.",
        },
        "href": {
            "label": "Target (href)",
            "description": "Filter on the href attribute of the element.",
            "examples": ["https://posthog.com/about"],
        },
    },
    "metadata": {
        "distinct_id": {
            "label": "Distinct ID",
            "description": "The current distinct ID of the user",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
    },
    "event_properties": {
        "distinct_id": {},
        "$session_duration": {},
        "$copy_type": {
            "label": "Copy Type",
            "description": "Type of copy event.",
            "examples": ["copy", "cut"],
        },
        "$selected_content": {
            "label": "Copied content",
            "description": "The content that was selected when the user copied or cut.",
        },
        "$set": {
            "label": "Set",
            "description": "Person properties to be set",
        },
        "$set_once": {
            "label": "Set Once",
            "description": "Person properties to be set if not set already (i.e. first-touch)",
        },
        "$pageview_id": {
            "label": "Pageview ID",
            "description": "PostHog's internal ID for matching events to a pageview.",
            "system": True,
        },
        "$autocapture_disabled_server_side": {
            "label": "Autocapture Disabled Server-Side",
            "description": "If autocapture has been disabled server-side.",
            "system": True,
        },
        "$console_log_recording_enabled_server_side": {
            "label": "Console Log Recording Enabled Server-Side",
            "description": "If console log recording has been enabled server-side.",
            "system": True,
        },
        "$session_recording_recorder_version_server_side": {
            "label": "Session Recording Recorder Version Server-Side",
            "description": "The version of the session recording recorder that is enabled server-side.",
            "examples": ["v2"],
            "system": True,
        },
        "$feature_flag_payloads": {
            "label": "Feature Flag Payloads",
            "description": "Feature flag payloads active in the environment.",
        },
        "$capture_failed_request": {
            "label": "Capture Failed Request",
            "description": "",
        },
        "$sentry_exception": {
            "label": "Sentry exception",
            "description": "Raw Sentry exception data",
            "system": True,
        },
        "$sentry_exception_message": {
            "label": "Sentry exception message",
        },
        "$sentry_exception_type": {
            "label": "Sentry exception type",
            "description": "Class name of the exception object",
        },
        "$sentry_tags": {
            "label": "Sentry tags",
            "description": "Tags sent to Sentry along with the exception",
        },
        "$exception_type": {
            "label": "Exception type",
            "description": 'Exception categorized into types. E.g. "Error"',
        },
        "$exception_message": {
            "label": "Exception Message",
            "description": "The message detected on the error.",
        },
        "$exception_source": {
            "label": "Exception source",
            "description": "The source of the exception. E.g. JS file.",
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
            "description": "Whether this was detected as a synthetic exception",
        },
        "$exception_stack_trace_raw": {
            "label": "Exception raw stack trace",
            "description": "The exception's stack trace, as a string.",
        },
        "$exception_handled": {
            "label": "Exception was handled",
            "description": "Whether this was a handled or unhandled exception",
        },
        "$exception_personURL": {
            "label": "Exception person URL",
            "description": "The PostHog person that experienced the exception",
        },
        "$ce_version": {
            "label": "$ce_version",
            "description": "",
            "system": True,
        },
        "$anon_distinct_id": {
            "label": "Anon Distinct ID",
            "description": "If the user was previously anonymous, their anonymous ID will be set here.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
            "system": True,
        },
        "$event_type": {
            "label": "Event Type",
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
            "description": "Use the HogQL field `timestamp` instead. This field was previously set on some client side events.",
            "system": True,
            "examples": ["1681211521.345"],
        },
        "$device_id": {
            "label": "Device ID",
            "description": "Unique ID for that device, consistent even if users are logging in/out.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
            "system": True,
        },
        "$geoip_city_name": {
            "label": "City Name",
            "description": "Name of the city matched to this event's IP address.",
            "examples": ["Sydney", "Chennai", "Brooklyn"],
        },
        "$geoip_country_name": {
            "label": "Country Name",
            "description": "Name of the country matched to this event's IP address.",
            "examples": ["Australia", "India", "United States"],
        },
        "$geoip_country_code": {
            "label": "Country Code",
            "description": "Code of the country matched to this event's IP address.",
            "examples": ["AU", "IN", "US"],
        },
        "$geoip_continent_name": {
            "label": "Continent Name",
            "description": "Name of the continent matched to this event's IP address.",
            "examples": ["Oceania", "Asia", "North America"],
        },
        "$geoip_continent_code": {
            "label": "Continent Code",
            "description": "Code of the continent matched to this event's IP address.",
            "examples": ["OC", "AS", "NA"],
        },
        "$geoip_postal_code": {
            "label": "Postal Code",
            "description": "Approximated postal code matched to this event's IP address.",
            "examples": ["2000", "600004", "11211"],
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
            "label": "Subdivision 1 Name",
            "description": "Name of the subdivision matched to this event's IP address.",
            "examples": ["New South Wales", "Tamil Nadu", "New York"],
        },
        "$geoip_subdivision_1_code": {
            "label": "Subdivision 1 Code",
            "description": "Code of the subdivision matched to this event's IP address.",
            "examples": ["NSW", "TN", "NY"],
        },
        "$geoip_subdivision_2_name": {
            "label": "Subdivision 2 Name",
            "description": "Name of the second subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_2_code": {
            "label": "Subdivision 2 Code",
            "description": "Code of the second subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_3_name": {
            "label": "Subdivision 3 Name",
            "description": "Name of the third subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_3_code": {
            "label": "Subdivision 3 Code",
            "description": "Code of the third subdivision matched to this event's IP address.",
        },
        "$geoip_disable": {
            "label": "GeoIP Disabled",
            "description": "Whether to skip GeoIP processing for the event.",
        },
        "$el_text": {
            "label": "Element Text",
            "description": "The text of the element that was clicked. Only sent with Autocapture events.",
            "examples": ["Click here!"],
        },
        "$app_build": {
            "label": "App Build",
            "description": "The build number for the app.",
        },
        "$app_name": {
            "label": "App Name",
            "description": "The name of the app.",
        },
        "$app_namespace": {
            "label": "App Namespace",
            "description": "The namespace of the app as identified in the app store.",
            "examples": ["com.posthog.app"],
        },
        "$app_version": {
            "label": "App Version",
            "description": "The version of the app.",
        },
        "$device_manufacturer": {
            "label": "Device Manufacturer",
            "description": "The manufacturer of the device",
            "examples": ["Apple", "Samsung"],
        },
        "$device_name": {
            "label": "Device Name",
            "description": "Name of the device",
            "examples": ["iPhone 12 Pro", "Samsung Galaxy 10"],
        },
        "$locale": {
            "label": "Locale",
            "description": "The locale of the device",
            "examples": ["en-US", "de-DE"],
        },
        "$os_name": {
            "label": "OS Name",
            "description": "The Operating System name",
            "examples": ["iOS", "Android"],
        },
        "$os_version": {
            "label": "OS Version",
            "description": "The Operating System version.",
            "examples": ["15.5"],
        },
        "$timezone": {
            "label": "Timezone",
            "description": "The timezone as reported by the device",
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
            "label": "Plugins Succeeded",
            "description": "Plugins that successfully processed the event, e.g. edited properties (plugin method processEvent).",
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
            "label": "Group Set",
            "description": "Group properties to be set",
        },
        "$group_key": {
            "label": "Group Key",
            "description": "Specified group key",
        },
        "$group_type": {
            "label": "Group Type",
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
            "label": "Plugins Failed",
            "description": "Plugins that failed to process the event (plugin method processEvent).",
        },
        "$plugins_deferred": {
            "label": "Plugins Deferred",
            "description": "Plugins to which the event was handed off post-ingestion, e.g. for export (plugin method onEvent).",
        },
        "$$plugin_metrics": {
            "label": "Plugin Metric",
            "description": "Performance metrics for a given plugin.",
        },
        "$creator_event_uuid": {
            "label": "Creator Event ID",
            "description": "Unique ID for the event, which created this person.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
        "utm_source": {
            "label": "UTM Source",
            "description": "UTM source tag.",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "$initial_utm_source": {
            "label": "Initial UTM Source",
            "description": "UTM source tag.",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "utm_medium": {
            "label": "UTM Medium",
            "description": "UTM medium tag.",
            "examples": ["Social", "Organic", "Paid", "Email"],
        },
        "utm_campaign": {
            "label": "UTM Campaign",
            "description": "UTM campaign tag.",
            "examples": ["feature launch", "discount"],
        },
        "utm_name": {
            "label": "UTM Name",
            "description": "UTM campaign tag, sent via Segment.",
            "examples": ["feature launch", "discount"],
        },
        "utm_content": {
            "label": "UTM Content",
            "description": "UTM content tag.",
            "examples": ["bottom link", "second button"],
        },
        "utm_term": {
            "label": "UTM Term",
            "description": "UTM term tag.",
            "examples": ["free goodies"],
        },
        "$performance_page_loaded": {
            "label": "Page Loaded",
            "description": "The time taken until the browser's page load event in milliseconds.",
        },
        "$performance_raw": {
            "label": "Browser Performance",
            "description": "The browser performance entries for navigation (the page), paint, and resources. That were available when the page view event fired",
            "system": True,
        },
        "$had_persisted_distinct_id": {
            "label": "$had_persisted_distinct_id",
            "description": "",
            "system": True,
        },
        "$sentry_event_id": {
            "label": "Sentry Event ID",
            "description": "This is the Sentry key for an event.",
            "examples": ["byroc2ar9ee4ijqp"],
            "system": True,
        },
        "$timestamp": {
            "label": "Timestamp",
            "description": "Time the event happened.",
            "examples": ["2023-05-20T15:30:00Z"],
        },
        "$sent_at": {
            "label": "Sent At",
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
            "label": "Browser Language",
            "description": "Language.",
            "examples": ["en", "en-US", "cn", "pl-PL"],
        },
        "$current_url": {
            "label": "Current URL",
            "description": "The URL visited at the time of the event.",
            "examples": ["https://example.com/interesting-article?parameter=true"],
        },
        "$browser_version": {
            "label": "Browser Version",
            "description": "The version of the browser that was used. Used in combination with Browser.",
            "examples": ["70", "79"],
        },
        "$raw_user_agent": {
            "label": "Raw User Agent",
            "description": "PostHog process information like browser, OS, and device type from the user agent string. This is the raw user agent string.",
            "examples": ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"],
        },
        "$user_agent": {
            "label": "Raw User Agent",
            "description": "Some SDKs (like Android) send the raw user agent as $user_agent.",
            "examples": ["Dalvik/2.1.0 (Linux; U; Android 11; Pixel 3 Build/RQ2A.210505.002)"],
        },
        "$screen_height": {
            "label": "Screen Height",
            "description": "The height of the user's entire screen (in pixels).",
            "examples": ["2160", "1050"],
        },
        "$screen_width": {
            "label": "Screen Width",
            "description": "The width of the user's entire screen (in pixels).",
            "examples": ["1440", "1920"],
        },
        "$screen_name": {
            "label": "Screen Name",
            "description": "The name of the active screen.",
        },
        "$viewport_height": {
            "label": "Viewport Height",
            "description": "The height of the user's actual browser window (in pixels).",
            "examples": ["2094", "1031"],
        },
        "$viewport_width": {
            "label": "Viewport Width",
            "description": "The width of the user's actual browser window (in pixels).",
            "examples": ["1439", "1915"],
        },
        "$lib": {
            "label": "Library",
            "description": "What library was used to send the event.",
            "examples": ["web", "posthog-ios"],
        },
        "$lib_custom_api_host": {
            "label": "Library Custom API Host",
            "description": "The custom API host used to send the event.",
            "examples": ["https://ph.example.com"],
        },
        "$lib_version": {
            "label": "Library Version",
            "description": "Version of the library used to send the event. Used in combination with Library.",
            "examples": ["1.0.3"],
        },
        "$lib_version__major": {
            "label": "Library Version (Major)",
            "description": "Major version of the library used to send the event.",
            "examples": [1],
        },
        "$lib_version__minor": {
            "label": "Library Version (Minor)",
            "description": "Minor version of the library used to send the event.",
            "examples": [0],
        },
        "$lib_version__patch": {
            "label": "Library Version (Patch)",
            "description": "Patch version of the library used to send the event.",
            "examples": [3],
        },
        "$referrer": {
            "label": "Referrer URL",
            "description": "URL of where the user came from.",
            "examples": ["https://google.com/search?q=posthog&rlz=1C..."],
        },
        "$referring_domain": {
            "label": "Referring Domain",
            "description": "Domain of where the user came from.",
            "examples": ["google.com", "facebook.com"],
        },
        "$user_id": {
            "label": "User ID",
            "description": "This variable will be set to the distinct ID if you've called posthog.identify('distinct id'). If the user is anonymous, it'll be empty.",
        },
        "$ip": {
            "label": "IP Address",
            "description": "IP address for this user when the event was sent.",
            "examples": ["203.0.113.0"],
        },
        "$host": {
            "label": "Host",
            "description": "The hostname of the Current URL.",
            "examples": ["example.com", "localhost:8000"],
        },
        "$pathname": {
            "label": "Path Name",
            "description": "The path of the Current URL, which means everything in the url after the domain.",
            "examples": ["/pricing", "/about-us/team"],
        },
        "$search_engine": {
            "label": "Search Engine",
            "description": "The search engine the user came in from (if any).",
            "examples": ["Google", "DuckDuckGo"],
        },
        "$active_feature_flags": {
            "label": "Active Feature Flags",
            "description": "Keys of the feature flags that were active while this event was sent.",
            "examples": ["['beta-feature']"],
        },
        "$enabled_feature_flags": {
            "label": "Enabled Feature Flags",
            "description": "Keys and multivariate values of the feature flags that were active while this event was sent.",
            "examples": ['{"flag": "value"}'],
        },
        "$feature_flag_response": {
            "label": "Feature Flag Response",
            "description": "What the call to feature flag responded with.",
            "examples": ["true", "false"],
        },
        "$feature_flag": {
            "label": "Feature Flag",
            "description": 'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag_called event. If you want to filter other events, try "Active Feature Flags".',
            "examples": ["beta-feature"],
        },
        "$survey_response": {
            "label": "Survey Response",
            "description": "The response value for the first question in the survey.",
            "examples": ["I love it!", 5, "['choice 1', 'choice 3']"],
        },
        "$survey_name": {
            "label": "Survey Name",
            "description": "The name of the survey.",
            "examples": ["Product Feedback for New Product", "Home page NPS"],
        },
        "$survey_questions": {
            "label": "Survey Questions",
            "description": "The questions asked in the survey.",
        },
        "$survey_id": {
            "label": "Survey ID",
            "description": "The unique identifier for the survey.",
        },
        "$survey_iteration": {
            "label": "Survey Iteration Number",
            "description": "The iteration number for the survey.",
        },
        "$survey_iteration_start_date": {
            "label": "Survey Iteration Start Date",
            "description": "The start date for the current iteration of the survey.",
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
            "label": "Device Type",
            "description": "The type of device that was used.",
            "examples": ["Mobile", "Tablet", "Desktop"],
        },
        "$screen_density": {
            "label": "Screen density",
            "description": 'The logical density of the display. This is a scaling factor for the Density Independent Pixel unit, where one DIP is one pixel on an approximately 160 dpi screen (for example a 240x320, 1.5"x2" screen), providing the baseline of the system\'s display. Thus on a 160dpi screen this density value will be 1; on a 120 dpi screen it would be .75; etc.',
            "examples": [2.75],
        },
        "$device_model": {
            "label": "Device Model",
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
            "label": "Referrer Host",
            "description": "Host that the user came from. (First-touch, session-scoped)",
            "examples": ["google.com", "facebook.com"],
        },
        "$client_session_initial_pathname": {
            "label": "Initial Path",
            "description": "Path that the user started their session on. (First-touch, session-scoped)",
            "examples": ["/register", "/some/landing/page"],
        },
        "$client_session_initial_utm_source": {
            "label": "Initial UTM Source",
            "description": "UTM Source. (First-touch, session-scoped)",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "$client_session_initial_utm_campaign": {
            "label": "Initial UTM Campaign",
            "description": "UTM Campaign. (First-touch, session-scoped)",
            "examples": ["feature launch", "discount"],
        },
        "$client_session_initial_utm_medium": {
            "label": "Initial UTM Medium",
            "description": "UTM Medium. (First-touch, session-scoped)",
            "examples": ["Social", "Organic", "Paid", "Email"],
        },
        "$client_session_initial_utm_content": {
            "label": "Initial UTM Source",
            "description": "UTM Source. (First-touch, session-scoped)",
            "examples": ["bottom link", "second button"],
        },
        "$client_session_initial_utm_term": {
            "label": "Initial UTM Source",
            "description": "UTM Source. (First-touch, session-scoped)",
            "examples": ["free goodies"],
        },
        "$network_carrier": {
            "label": "Network Carrier",
            "description": "The network carrier that the user is on.",
            "examples": ["cricket", "telecom"],
        },
        "from_background": {
            "label": "From Background",
            "description": "Whether the app was opened for the first time or from the background.",
            "examples": ["true", "false"],
        },
        "url": {
            "label": "URL",
            "description": "The deep link URL that the app was opened from.",
            "examples": ["https://open.my.app"],
        },
        "referring_application": {
            "label": "Referrer Application",
            "description": "The namespace of the app that made the request.",
            "examples": ["com.posthog.app"],
        },
        "version": {
            "label": "App Version",
            "description": "The version of the app",
            "examples": ["1.0.0"],
        },
        "previous_version": {
            "label": "App Previous Version",
            "description": "The previous version of the app",
            "examples": ["1.0.0"],
        },
        "build": {
            "label": "App Build",
            "description": "The build number for the app",
            "examples": ["1"],
        },
        "previous_build": {
            "label": "App Previous Build",
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
            "label": "Is Identified",
            "description": "When the person was identified",
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
    },
    "numerical_event_properties": {},
    "person_properties": {},
    "session_properties": {
        "$session_duration": {
            "label": "Session duration",
            "description": "The duration of the session being tracked. Learn more about how PostHog tracks sessions in our documentation.\n\nNote, if the duration is formatted as a single number (not 'HH:MM:SS'), it's in seconds.",
            "examples": ["01:04:12"],
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
            "description": "The timestamp of the last event from this session",
            "examples": ["2023-05-20T16:30:00Z"],
            "type": "DateTime",
        },
        "$entry_current_url": {
            "label": "Entry URL",
            "description": "The first URL visited in this session",
            "examples": ["https://example.com/interesting-article?parameter=true"],
            "type": "String",
        },
        "$entry_pathname": {
            "label": "Entry pathname",
            "description": "The first pathname visited in this session",
            "examples": ["/interesting-article?parameter=true"],
            "type": "String",
        },
        "$end_current_url": {
            "label": "Entry URL",
            "description": "The first URL visited in this session",
            "examples": ["https://example.com/interesting-article?parameter=true"],
            "type": "String",
        },
        "$end_pathname": {
            "label": "Entry pathname",
            "description": "The first pathname visited in this session",
            "examples": ["/interesting-article?parameter=true"],
            "type": "String",
        },
        "$exit_current_url": {
            "label": "Exit URL",
            "description": "The last URL visited in this session",
            "examples": ["https://example.com/interesting-article?parameter=true"],
            "type": "String",
        },
        "$exit_pathname": {
            "label": "Exit pathname",
            "description": "The last pathname visited in this session",
            "examples": ["/interesting-article?parameter=true"],
            "type": "String",
        },
        "$pageview_count": {
            "label": "Pageview count",
            "description": "The number of page view events in this session",
            "examples": ["123"],
            "type": "Numeric",
        },
        "$autocapture_count": {
            "label": "Autocapture count",
            "description": "The number of autocapture events in this session",
            "examples": ["123"],
            "type": "Numeric",
        },
        "$screen_count": {
            "label": "Screen count",
            "description": "The number of screen events in this session",
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
    },
    "groups": {
        "$group_key": {
            "label": "Group Key",
            "description": "Specified group key",
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
    },
}
