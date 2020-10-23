import datetime
import json

from py_mini_racer import py_mini_racer

from posthog.plugins.models import PluginBaseClass, PosthogEvent, TeamPlugin


class JSPlugin(PluginBaseClass):
    def __init__(self, config: TeamPlugin):
        super(JSPlugin, self).__init__(config)
        print("!!!! JS INIT")
        self.ctx = py_mini_racer.MiniRacer()
        self.ctx.eval(config.plugin_module.index_js)

        # self.ctx.attach('console.log', proc{ |*args| puts('LOG> ' + args.map(&:to_s).join(' ')) })

        self.js_hooks = self.ctx.eval("this")

    def _get_meta(self):
        return {
            "team": self.config.team,
            "plugin": self.config.plugin,
            "order": self.config.order,
            "name": self.config.name,
            "tag": self.config.tag,
            "config": self.config.config,
        }

    # Called before any event is processed
    def _process_hook(self, hook: str, event: PosthogEvent):
        if not self.js_hooks.get(hook, None):
            return event

        event_dict = {
            "ip": event.ip,
            "site_url": event.site_url,
            "event": event.event,
            "distinct_id": event.distinct_id,
            "team_id": event.team_id,
            "properties": event.properties,
            "timestamp": event.timestamp.timestamp(),
        }
        event_response = self.ctx.eval("{}({}, {})".format(hook, json.dumps(event_dict), json.dumps(self._get_meta)))
        if event_response:
            event.ip = event_response["ip"]
            event.site_url = event_response["site_url"]
            event.event = event_response["event"]
            event.distinct_id = event_response["distinct_id"]
            event.properties = event_response["properties"]
            event.timestamp = datetime.datetime.fromtimestamp(event_response["timestamp"])
            return event

        return None

    # Called before any event is processed
    def process_event(self, event: PosthogEvent):
        return self._process_hook("process_event", event)

    # Called before any alias event is processed
    def process_alias(self, event: PosthogEvent):
        return self._process_hook("process_alias", event)

    # Called before any identify is processed
    def process_identify(self, event: PosthogEvent):
        return self._process_hook("process_identify", event)
