from decimal import Decimal
from unittest.mock import ANY, patch
from inline_snapshot import snapshot
import pytest
from posthog.models.action.action import Action
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feedback.survey import Survey
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.plugin import Plugin, PluginConfig, PluginSourceFile
from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig, cache_key_for_team_token
from posthog.test.base import BaseTest
from django.core.cache import cache


class _RemoteConfigBase(BaseTest):
    remote_config: RemoteConfig

    def setUp(self):
        super().setUp()

        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )
        self.team = team
        self.team.api_token = "phc_12345"  # Easier to test against
        self.team.save()

        # There will always be a config thanks to the signal
        self.remote_config = RemoteConfig.objects.get(team=self.team)


class TestRemoteConfig(_RemoteConfigBase):
    def test_creates_remote_config_immediately(self):
        assert self.remote_config
        assert self.remote_config.updated_at
        assert self.remote_config.synced_at

        assert self.remote_config.config == snapshot(
            {
                "token": "phc_12345",
                "surveys": False,
                "heatmaps": False,
                "siteApps": [],
                "analytics": {"endpoint": "/i/v0/e/"},
                "hasFeatureFlags": False,
                "sessionRecording": False,
                "captureDeadClicks": False,
                "capturePerformance": {"web_vitals": False, "network_timing": True, "web_vitals_allowed_metrics": None},
                "autocapture_opt_out": False,
                "supportedCompression": ["gzip", "gzip-js"],
                "autocaptureExceptions": False,
                "defaultIdentifiedOnly": False,
                "elementsChainAsString": True,
            }
        )

    def test_indicates_if_feature_flags_exist(self):
        assert not self.remote_config.config["hasFeatureFlags"]

        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={},
            name="TestFlag",
            key="test-flag",
            created_by=self.user,
            deleted=True,
        )

        assert not self.remote_config.config["hasFeatureFlags"]
        flag.active = False
        flag.deleted = False
        flag.save()
        self.remote_config.refresh_from_db()
        assert not self.remote_config.config["hasFeatureFlags"]
        flag.active = True
        flag.deleted = False
        flag.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["hasFeatureFlags"]

    def test_capture_dead_clicks_toggle(self):
        self.team.capture_dead_clicks = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["captureDeadClicks"]

    def test_capture_performance_toggle(self):
        self.team.capture_performance_opt_in = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["capturePerformance"]["network_timing"]

    def test_autocapture_opt_out_toggle(self):
        self.team.autocapture_opt_out = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["autocapture_opt_out"]

    def test_autocapture_exceptions_toggle(self):
        self.team.autocapture_exceptions_opt_in = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["autocaptureExceptions"] == {"endpoint": "/e/"}

    def test_session_recording_sample_rate(self):
        self.team.session_recording_opt_in = True
        self.team.session_recording_sample_rate = Decimal("0.5")
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["sessionRecording"]["sampleRate"] == "0.50"


class TestRemoteConfigSurveys(_RemoteConfigBase):
    # Largely copied from TestSurveysAPIList
    def setUp(self):
        super().setUp()

        self.team.save()

    def test_includes_survey_config(self):
        survey_appearance = {
            "thankYouMessageHeader": "Thanks for your feedback!",
            "thankYouMessageDescription": "We'll use it to make notebooks better",
        }

        self.team.survey_config = {"appearance": survey_appearance}
        self.team.save()

        self.remote_config.refresh_from_db()
        assert self.remote_config.config["surveys"] == snapshot(
            {
                "surveys": [],
                "survey_config": {
                    "appearance": {
                        "thankYouMessageHeader": "Thanks for your feedback!",
                        "thankYouMessageDescription": "We'll use it to make notebooks better",
                    }
                },
            }
        )

    def test_includes_range_of_survey_types(self):
        survey_basic = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Basic survey",
            description="This should not be included",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
        )
        linked_flag = FeatureFlag.objects.create(team=self.team, key="linked-flag", created_by=self.user)
        targeting_flag = FeatureFlag.objects.create(team=self.team, key="targeting-flag", created_by=self.user)
        internal_targeting_flag = FeatureFlag.objects.create(
            team=self.team, key="custom-targeting-flag", created_by=self.user
        )

        survey_with_flags = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey with flags",
            type="popover",
            linked_flag=linked_flag,
            targeting_flag=targeting_flag,
            internal_targeting_flag=internal_targeting_flag,
            questions=[{"type": "open", "question": "What's a hedgehog?"}],
        )

        action = Action.objects.create(
            team=self.team,
            name="user subscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        survey_with_actions = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="survey with actions",
            type="popover",
            questions=[{"type": "open", "question": "Why's a hedgehog?"}],
        )
        survey_with_actions.actions.set(Action.objects.filter(name="user subscribed"))
        survey_with_actions.save()

        self.remote_config.refresh_from_db()
        assert self.remote_config.config["surveys"]
        # TODO: Fix this - there is _waaaay_ too much data in here
        assert self.remote_config.config["surveys"] == {
            "surveys": [
                {
                    "id": str(survey_basic.id),
                    "name": "Basic survey",
                    "type": "popover",
                    "end_date": None,
                    "questions": [{"type": "open", "question": "What's a survey?"}],
                    "appearance": None,
                    "conditions": None,
                    "start_date": None,
                    "current_iteration": None,
                    "current_iteration_start_date": None,
                },
                {
                    "id": str(survey_with_flags.id),
                    "name": "Survey with flags",
                    "type": "popover",
                    "end_date": None,
                    "questions": [{"type": "open", "question": "What's a hedgehog?"}],
                    "appearance": None,
                    "conditions": None,
                    "start_date": None,
                    "linked_flag_key": "linked-flag",
                    "current_iteration": None,
                    "targeting_flag_key": "targeting-flag",
                    "internal_targeting_flag_key": "custom-targeting-flag",
                    "current_iteration_start_date": None,
                },
                {
                    "id": str(survey_with_actions.id),
                    "name": "survey with actions",
                    "type": "popover",
                    "end_date": None,
                    "questions": [{"type": "open", "question": "Why's a hedgehog?"}],
                    "appearance": None,
                    "conditions": {
                        "actions": {
                            "values": [
                                {
                                    "id": action.id,
                                    "steps": [
                                        {
                                            "url": "docs",
                                            "href": None,
                                            "text": None,
                                            "event": "$pageview",
                                            "selector": None,
                                            "tag_name": None,
                                            "properties": None,
                                            "url_matching": "contains",
                                            "href_matching": None,
                                            "text_matching": None,
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                    "start_date": None,
                    "current_iteration": None,
                    "current_iteration_start_date": None,
                },
            ],
            "survey_config": None,
        }


class TestRemoteConfigCaching(_RemoteConfigBase):
    def setUp(self):
        super().setUp()
        self.remote_config.refresh_from_db()
        # Clear the cache so we are properly testing each flow
        assert cache.delete(cache_key_for_team_token(self.team.api_token, "config"))
        assert cache.delete(cache_key_for_team_token(self.team.api_token, "config.js"))

    def test_syncs_if_changes(self):
        synced_at = self.remote_config.synced_at
        self.remote_config.config["surveys"] = True
        self.remote_config.sync()
        assert synced_at < self.remote_config.synced_at  # type: ignore

    def test_persists_data_to_redis_on_sync(self):
        self.remote_config.config["surveys"] = True
        self.remote_config.sync()
        assert cache.get(cache_key_for_team_token(self.team.api_token, "config"))
        assert cache.get(cache_key_for_team_token(self.team.api_token, "config.js"))

    def test_gets_via_redis_cache(self):
        with self.assertNumQueries(2):
            data = RemoteConfig.get_config_via_token(self.team.api_token)
        assert data == self.remote_config.config

        with self.assertNumQueries(0):
            data = RemoteConfig.get_config_via_token(self.team.api_token)
        assert data == self.remote_config.config

    def test_gets_js_via_redis_cache(self):
        with self.assertNumQueries(3):
            data = RemoteConfig.get_config_js_via_token(self.team.api_token)

        assert data == self.remote_config.build_js_config()

        with self.assertNumQueries(0):
            data = RemoteConfig.get_config_js_via_token(self.team.api_token)

        assert data == self.remote_config.build_js_config()

    @patch("posthog.models.remote_config.get_array_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_gets_array_js_via_redis_cache(self, mock_get_array_js_content):
        with self.assertNumQueries(3):
            RemoteConfig.get_array_js_via_token(self.team.api_token)

        with self.assertNumQueries(0):
            RemoteConfig.get_array_js_via_token(self.team.api_token)

    def test_caches_missing_response(self):
        with self.assertNumQueries(1):
            with pytest.raises(RemoteConfig.DoesNotExist):
                RemoteConfig.get_array_js_via_token("missing-token")

        with self.assertNumQueries(0):
            with pytest.raises(RemoteConfig.DoesNotExist):
                RemoteConfig.get_array_js_via_token("missing-token")


class TestRemoteConfigJS(_RemoteConfigBase):
    def test_renders_js_including_config(self):
        # NOTE: This is a very basic test to check that the JS is rendered correctly
        # It doesn't check the actual contents of the JS, as that changes often but checks some general things
        js = self.remote_config.build_config()
        js = self.remote_config.build_js_config()

        # TODO: Come up with a good way of solidly testing this...
        assert js == snapshot(
            """\
(function() {
  window._POSTHOG_CONFIG = {"token": "phc_12345", "surveys": false, "heatmaps": false, "siteApps": [], "analytics": {"endpoint": "/i/v0/e/"}, "hasFeatureFlags": false, "sessionRecording": false, "captureDeadClicks": false, "capturePerformance": {"web_vitals": false, "network_timing": true, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "supportedCompression": ["gzip", "gzip-js"], "autocaptureExceptions": false, "defaultIdentifiedOnly": false, "elementsChainAsString": true};
  window._POSTHOG_JS_APPS = [];
})();\
"""
        )

    def test_renders_js_including_site_apps(self):
        files = [
            "(function () { return { inject: (data) => console.log('injected!', data)}; })",
            "(function () { return { inject: (data) => console.log('injected 2!', data)}; })",
            "(function () { return { inject: (data) => console.log('injected but disabled!', data)}; })",
        ]

        plugin_configs = []

        for transpiled in files:
            plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
            PluginSourceFile.objects.create(
                plugin=plugin,
                filename="site.ts",
                source="IGNORED FOR TESTING",
                transpiled=transpiled,
                status=PluginSourceFile.Status.TRANSPILED,
            )
            plugin_configs.append(
                PluginConfig.objects.create(
                    plugin=plugin,
                    enabled=True,
                    order=1,
                    team=self.team,
                    config={},
                    web_token="tokentoken",
                )
            )

        plugin_configs[2].enabled = False

        self.remote_config.build_config()
        js = self.remote_config.build_js_config()

        # TODO: Come up with a good way of solidly testing this, ideally by running it in an actual browser environment
        assert js == snapshot(
            """\
(function() {
  window._POSTHOG_CONFIG = {"token": "phc_12345", "surveys": false, "heatmaps": false, "siteApps": [], "analytics": {"endpoint": "/i/v0/e/"}, "hasFeatureFlags": false, "sessionRecording": false, "captureDeadClicks": false, "capturePerformance": {"web_vitals": false, "network_timing": true, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "supportedCompression": ["gzip", "gzip-js"], "autocaptureExceptions": false, "defaultIdentifiedOnly": false, "elementsChainAsString": true};
  window._POSTHOG_JS_APPS = [    
    {
      id: 'tokentoken',
      init: function(config) {
            (function () { return { inject: (data) => console.log('injected!', data)}; })().inject({ config:{}, posthog:config.posthog });
        config.callback();
      }
    },    
    {
      id: 'tokentoken',
      init: function(config) {
            (function () { return { inject: (data) => console.log('injected 2!', data)}; })().inject({ config:{}, posthog:config.posthog });
        config.callback();
      }
    },    
    {
      id: 'tokentoken',
      init: function(config) {
            (function () { return { inject: (data) => console.log('injected but disabled!', data)}; })().inject({ config:{}, posthog:config.posthog });
        config.callback();
      }
    }];
})();\
"""  # noqa: W291, W293
        )

    def test_renders_js_including_site_functions(self):
        non_site_app = HogFunction.objects.create(
            name="Test",
            type=HogFunctionType.DESTINATION,
            team=self.team,
            enabled=True,
            filters={
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                "filter_test_accounts": True,
            },
        )

        site_destination = HogFunction.objects.create(
            name="Test",
            type=HogFunctionType.SITE_DESTINATION,
            team=self.team,
            enabled=True,
            filters={
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                "filter_test_accounts": True,
            },
        )

        site_app = HogFunction.objects.create(
            name="Test",
            type=HogFunctionType.SITE_APP,
            team=self.team,
            enabled=True,
        )

        self.remote_config.build_config()
        js = self.remote_config.build_js_config()
        assert str(non_site_app.id) not in js
        assert str(site_destination.id) in js
        assert str(site_app.id) in js

        js = js.replace(str(non_site_app.id), "NON_SITE_APP_ID")
        js = js.replace(str(site_destination.id), "SITE_DESTINATION_ID")
        js = js.replace(str(site_app.id), "SITE_APP_ID")

        # TODO: Come up with a good way of solidly testing this, ideally by running it in an actual browser environment
        assert js == snapshot(
            """\
(function() {
  window._POSTHOG_CONFIG = {"token": "phc_12345", "surveys": false, "heatmaps": false, "siteApps": [], "analytics": {"endpoint": "/i/v0/e/"}, "hasFeatureFlags": false, "sessionRecording": false, "captureDeadClicks": false, "capturePerformance": {"web_vitals": false, "network_timing": true, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "supportedCompression": ["gzip", "gzip-js"], "autocaptureExceptions": false, "defaultIdentifiedOnly": false, "elementsChainAsString": true};
  window._POSTHOG_JS_APPS = [    
    {
      id: 'SITE_DESTINATION_ID',
      init: function(config) { return     (function() {
        function toString (value) { return __STLToString(value) }
        function match (str, pattern) { return !str || !pattern ? false : new RegExp(pattern).test(str) }
        function ilike (str, pattern) { return __like(str, pattern, true) }
        function __like(str, pattern, caseInsensitive = false) {
            if (caseInsensitive) {
                str = str.toLowerCase()
                pattern = pattern.toLowerCase()
            }
            pattern = String(pattern)
                .replaceAll(/[-/\\\\^$*+?.()|[\\]{}]/g, '\\\\$&')
                .replaceAll('%', '.*')
                .replaceAll('_', '.')
            return new RegExp(pattern).test(str)
        }
        function __getProperty(objectOrArray, key, nullish) {
            if ((nullish && !objectOrArray) || key === 0) { return null }
            if (Array.isArray(objectOrArray)) { return key > 0 ? objectOrArray[key - 1] : objectOrArray[objectOrArray.length + key] }
            else { return objectOrArray[key] }
        }
        function __STLToString(arg) {
            if (arg && __isHogDate(arg)) { return `${arg.year}-${arg.month.toString().padStart(2, '0')}-${arg.day.toString().padStart(2, '0')}`; }
            else if (arg && __isHogDateTime(arg)) { return __DateTimeToString(arg); }
            return __printHogStringOutput(arg); }
        function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) }
        function __printHogValue(obj, marked = new Set()) {
            if (typeof obj === 'object' && obj !== null && obj !== undefined) {
                if (marked.has(obj) && !__isHogDateTime(obj) && !__isHogDate(obj) && !__isHogError(obj)) { return 'null'; }
                marked.add(obj);
                try {
                    if (Array.isArray(obj)) {
                        if (obj.__isHogTuple) { return obj.length < 2 ? `tuple(${obj.map((o) => __printHogValue(o, marked)).join(', ')})` : `(${obj.map((o) => __printHogValue(o, marked)).join(', ')})`; }
                        return `[${obj.map((o) => __printHogValue(o, marked)).join(', ')}]`;
                    }
                    if (__isHogDateTime(obj)) { const millis = String(obj.dt); return `DateTime(${millis}${millis.includes('.') ? '' : '.0'}, ${__escapeString(obj.zone)})`; }
                    if (__isHogDate(obj)) return `Date(${obj.year}, ${obj.month}, ${obj.day})`;
                    if (__isHogError(obj)) { return `${String(obj.type)}(${__escapeString(obj.message)}${obj.payload ? `, ${__printHogValue(obj.payload, marked)}` : ''})`; }
                    if (obj instanceof Map) { return `{${Array.from(obj.entries()).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`; }
                    return `{${Object.entries(obj).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`;
                } finally {
                    marked.delete(obj);
                }
            } else if (typeof obj === 'boolean') return obj ? 'true' : 'false';
            else if (obj === null || obj === undefined) return 'null';
            else if (typeof obj === 'string') return __escapeString(obj);
                    if (typeof obj === 'function') return `fn<${__escapeIdentifier(obj.name || 'lambda')}(${obj.length})>`;
            return obj.toString();
        }
        function __isHogError(obj) {return obj && obj.__hogError__ === true}
        function __escapeString(value) {
            const singlequoteEscapeCharsMap = { '\\b': '\\\\b', '\\f': '\\\\f', '\\r': '\\\\r', '\\n': '\\\\n', '\\t': '\\\\t', '\\0': '\\\\0', '\\v': '\\\\v', '\\\\': '\\\\\\\\', "'": "\\\\'" }
            return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
        }
        function __escapeIdentifier(identifier) {
            const backquoteEscapeCharsMap = { '\\b': '\\\\b', '\\f': '\\\\f', '\\r': '\\\\r', '\\n': '\\\\n', '\\t': '\\\\t', '\\0': '\\\\0', '\\v': '\\\\v', '\\\\': '\\\\\\\\', '`': '\\\\`' }
            if (typeof identifier === 'number') return identifier.toString();
            if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
            return `\\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\\``;
        }
        function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
        function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
        function __DateTimeToString(dt) {
            if (__isHogDateTime(dt)) {
                const date = new Date(dt.dt * 1000);
                const timeZone = dt.zone || 'UTC';
                const milliseconds = Math.floor(dt.dt * 1000 % 1000);
                const options = { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
                const formatter = new Intl.DateTimeFormat('en-US', options);
                const parts = formatter.formatToParts(date);
                let year, month, day, hour, minute, second;
                for (const part of parts) {
                    switch (part.type) {
                        case 'year': year = part.value; break;
                        case 'month': month = part.value; break;
                        case 'day': day = part.value; break;
                        case 'hour': hour = part.value; break;
                        case 'minute': minute = part.value; break;
                        case 'second': second = part.value; break;
                        default: break;
                    }
                }
                const getOffset = (date, timeZone) => {
                    const tzDate = new Date(date.toLocaleString('en-US', { timeZone }));
                    const utcDate = new Date(date.toLocaleString('en-US', { timeZone: 'UTC' }));
                    const offset = (tzDate - utcDate) / 60000; // in minutes
                    const sign = offset >= 0 ? '+' : '-';
                    const absOffset = Math.abs(offset);
                    const hours = Math.floor(absOffset / 60);
                    const minutes = absOffset % 60;
                    return `${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
                };
                let offset = 'Z';
                if (timeZone !== 'UTC') {
                    offset = getOffset(date, timeZone);
                }
                let isoString = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
                isoString += `.${milliseconds.toString().padStart(3, '0')}`;
                isoString += offset;
                return isoString;
            }
        }
        function buildInputs(globals, initial) {
        let inputs = {
        };
        let __getGlobal = (key) => key === 'inputs' ? inputs : globals[key];
        return inputs;}
        const source = (function () {let exports={};"use strict";;return exports;})();
            let processEvent = undefined;
            if ('onEvent' in source) {
                processEvent = function processEvent(globals) {
                    if (!('onEvent' in source)) { return; };
                    const inputs = buildInputs(globals);
                    const filterGlobals = { ...globals.groups, ...globals.event, person: globals.person, inputs, pdi: { distinct_id: globals.event.distinct_id, person: globals.person } };
                    let __getGlobal = (key) => filterGlobals[key];
                    const filterMatches = !!(!!(!ilike(__getProperty(__getProperty(__getGlobal("person"), "properties", true), "email", true), "%@posthog.com%") && ((!match(toString(__getProperty(__getGlobal("properties"), "$host", true)), "^(localhost|127\\\\.0\\\\.0\\\\.1)($|:)")) ?? 1) && (__getGlobal("event") == "$pageview")));
                    if (filterMatches) { source.onEvent({ ...globals, inputs, posthog }); }
                }
            }
        
            function init(config) {
                const posthog = config.posthog;
                const callback = config.callback;
                if ('onLoad' in source) {
                    const r = source.onLoad({ inputs: buildInputs({}, true), posthog: posthog });
                    if (r && typeof r.then === 'function' && typeof r.finally === 'function') { r.catch(() => callback(false)).then(() => callback(true)) } else { callback(true) }
                } else {
                    callback(true);
                }
        
                return {
                    processEvent: processEvent
                }
            }
        
            return { init: init };
        })().init(config) } 
    },    
    {
      id: 'SITE_APP_ID',
      init: function(config) { return     (function() {
        
        function buildInputs(globals, initial) {
        let inputs = {
        };
        let __getGlobal = (key) => key === 'inputs' ? inputs : globals[key];
        return inputs;}
        const source = (function () {let exports={};"use strict";;return exports;})();
            let processEvent = undefined;
            if ('onEvent' in source) {
                processEvent = function processEvent(globals) {
                    if (!('onEvent' in source)) { return; };
                    const inputs = buildInputs(globals);
                    const filterGlobals = { ...globals.groups, ...globals.event, person: globals.person, inputs, pdi: { distinct_id: globals.event.distinct_id, person: globals.person } };
                    let __getGlobal = (key) => filterGlobals[key];
                    const filterMatches = true;
                    if (filterMatches) { source.onEvent({ ...globals, inputs, posthog }); }
                }
            }
        
            function init(config) {
                const posthog = config.posthog;
                const callback = config.callback;
                if ('onLoad' in source) {
                    const r = source.onLoad({ inputs: buildInputs({}, true), posthog: posthog });
                    if (r && typeof r.then === 'function' && typeof r.finally === 'function') { r.catch(() => callback(false)).then(() => callback(true)) } else { callback(true) }
                } else {
                    callback(true);
                }
        
                return {
                    processEvent: processEvent
                }
            }
        
            return { init: init };
        })().init(config) } 
    }];
})();\
"""  # noqa: W291, W293
        )
