import json
from dataclasses import dataclass
from typing import List, Optional

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from statshog.defaults.django import statsd

from posthog.logging.timing import timed
from posthog.models import PluginConfig, Team
from posthog.models.plugin import PluginSourceFile
from posthog.utils import cors_response


@dataclass
class SourceFile:
    id: int
    source: str
    token: str
    config_schema: dict
    config: dict


@csrf_exempt
@timed("posthog_cloud_web_js_endpoint")
def get_web_js(request: HttpRequest, id: int, token: str):
    # handle cors request
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": 1}))

    response = ""
    source_file = get_source_file(id, token) if token else None
    if source_file:
        id = source_file.id
        source = source_file.source
        config = get_web_config_from_schema(source_file.config_schema, source_file.config)
        response = f"{source}().inject({{config:{json.dumps(config)},posthog:window['__$$ph_web_js_{id}']}})"

    statsd.incr(f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "web_js"})
    return cors_response(request, HttpResponse(content=response, content_type="application/javascript"))


def get_decide_web_js_inject(team: Team):
    return [
        {
            "id": source_file.id,
            "source": get_bootloader(source_file.id, source_file.token),
            "config": None,
        }
        if requires_bootloader(source_file.source)
        else {
            "id": source_file.id,
            "source": source_file.source,
            "config": get_web_config_from_schema(source_file.config_schema, source_file.config),
        }
        for source_file in get_source_files(team)
    ]


def get_web_config_from_schema(config_schema: Optional[dict], config: Optional[dict]):
    if not config or not config_schema:
        return {}
    return {
        schema_element["key"]: config.get(schema_element["key"], schema_element.get("default", None))
        for schema_element in config_schema
        if schema_element.get("web", False) and schema_element.get("key", False)
    }


def requires_bootloader(source: Optional[str]):
    return source and len(source) >= 1024


def get_bootloader(id: int, token: str):
    return (
        f"(function(h){{return{{inject:function(opts){{"
        f"var s=document.createElement('script');"
        f"s.src=[h,h[h.length-1]==='/'?'':'/','web_js/',{id},'/',{json.dumps(token)},'/'].join('');"
        f"window['__$$ph_web_js_{id}']=opts.posthog;"
        f"document.head.appendChild(s);"
        f"}}}}}})"
    )


def get_source_file(id: int, token: str) -> Optional[SourceFile]:
    response = (
        PluginConfig.objects.filter(
            id=id,
            web_token=token,
            enabled=True,
            plugin__pluginsourcefile__filename="web.ts",
            plugin__pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
        )
        .values_list("id", "plugin__pluginsourcefile__transpiled", "web_token", "plugin__config_schema", "config")
        .first()
    )

    if not response:
        return None

    return SourceFile(*(list(response)))  # type: ignore


def get_source_files(team: Team) -> List[SourceFile]:
    sources = (
        PluginConfig.objects.filter(
            team=team,
            enabled=True,
            plugin__pluginsourcefile__filename="web.ts",
            plugin__pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
        )
        .values_list("id", "plugin__pluginsourcefile__transpiled", "web_token", "plugin__config_schema", "config")
        .all()
    )
    return [SourceFile(*(list(source))) for source in sources]  # type: ignore
