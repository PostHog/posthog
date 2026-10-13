"""Starter content for a freshly provisioned home canvas.

A new home grid should not open onto an empty lattice: provisioning seeds one
"Welcome checklist" component so the first thing a new user sees is a working
widget that walks them through setup. The checklist keeps its ticks in
``ph.state`` (user scope), pre-seeded with what the account already tells us:
they are reading it inside the desktop app, and whether the team has the
GitHub integration.
"""

from typing import Any
from uuid import UUID

import structlog

from posthog.models.integration import Integration
from posthog.models.user import User

from products.canvas.backend import build_service
from products.canvas.backend.layout import default_layout
from products.canvas.backend.models import Canvas, CanvasState
from products.canvas.backend.source import synthetic_source_project

logger = structlog.get_logger(__name__)

WELCOME_COMPONENT_NAME = "Welcome checklist"
WELCOME_STATE_KEY = "checked"

_CHECKLIST_CODE = """\
import { useEffect, useState } from "react";
import {
  Button,
  Checkbox,
  Label,
  SkeletonText,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { Info } from "lucide-react";

const ITEMS = [
  {
    id: "download-desktop",
    label: "Download PostHog Desktop",
    hint: null,
  },
  {
    id: "connect-github",
    label: "Connect GitHub",
    hint: "Connect a repository in settings so agents can open pull requests for you.",
  },
  {
    id: "add-widget",
    label: "Add a widget to this canvas",
    hint: "Select Edit in the top right, then click and drag anywhere on the dotted grid and describe what should go there.",
  },
  {
    id: "create-space",
    label: "Create your first space",
    hint: "Spaces organize work with your team. Open the spaces list in the sidebar and select New space.",
  },
  {
    id: "start-task",
    label: "Start your first task",
    hint: "Open a space and tell the agent what you want done. It picks the task up and reports back.",
  },
];

// Persistence needs both the SDK surface and a host that answers it. An old
// runtime without ph.state must degrade to session-only ticks, never crash
// the tile.
const stateApi =
  typeof ph !== "undefined" && ph.state && typeof ph.state.get === "function"
    ? ph.state
    : null;

export default function WelcomeChecklist() {
  const [checked, setChecked] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (!stateApi) {
      setChecked({ "download-desktop": true });
    } else {
      stateApi
        .get("checked", { scope: "user" })
        .then((value) => {
          if (!cancelled) {
            setChecked(value && typeof value === "object" ? value : {});
          }
        })
        .catch(() => {
          if (!cancelled) {
            setChecked({});
          }
        });
    }
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = (id, value) => {
    if (!checked) {
      return;
    }
    const next = { ...checked, [id]: value };
    setChecked(next);
    if (stateApi) {
      stateApi.set("checked", next, { scope: "user" }).catch(() => {});
    }
  };

  const done = checked ? ITEMS.filter((item) => checked[item.id]).length : 0;

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-3">
      <div className="flex items-baseline justify-between gap-2">
        <Text weight="medium">Welcome to PostHog</Text>
        {checked ? (
          <Text size="sm" className="text-muted-foreground">
            {done} of {ITEMS.length} done
          </Text>
        ) : null}
      </div>
      {checked === null ? (
        <SkeletonText lines={5} className="text-sm" />
      ) : (
        <div className="flex flex-col gap-1.5">
          {ITEMS.map((item) => (
            <div key={item.id} className="flex items-center gap-2">
              <Checkbox
                id={"checklist-" + item.id}
                checked={!!checked[item.id]}
                onCheckedChange={(value) => toggle(item.id, value === true)}
              />
              <Label
                htmlFor={"checklist-" + item.id}
                className={
                  "text-sm" +
                  (checked[item.id] ? " text-muted-foreground line-through" : "")
                }
              >
                {item.label}
              </Label>
              {item.hint ? (
                <Tooltip>
                  {/* A focusable button, not a bare icon: the tooltip carries the
                      only instructions for the step, so it has to be reachable
                      by keyboard and have a name a screen reader can announce. */}
                  <TooltipTrigger
                    render={
                      <Button
                        variant="link-muted"
                        size="icon-xs"
                        className="shrink-0"
                        aria-label={"More about " + item.label}
                      />
                    }
                  >
                    <Info />
                  </TooltipTrigger>
                  <TooltipContent>
                    <div className="max-w-60">{item.hint}</div>
                  </TooltipContent>
                </Tooltip>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
"""


def welcome_checklist_project() -> dict[str, Any]:
    """The checklist component's source project (kept publishable by a contract test)."""
    project = synthetic_source_project(_CHECKLIST_CODE)
    # The complete capability shape, not just the fields the checklist uses:
    # the builder freezes this verbatim into the artifact manifest, and older
    # clients parse the manifest with every field required.
    project["capabilities"] = {
        "posthog": {
            "insights": [],
            "inlineQueries": False,
            "captureEvents": [],
            "state": ["user"],
            "actions": [],
        },
        "network": {"origins": []},
    }
    project["component"] = {"size": {"defaultW": 2, "defaultH": 5, "minW": 2, "minH": 3}}
    return project


def seed_home_canvas(canvas: Canvas, *, user: User, channel_id: UUID) -> None:
    """Publish the welcome checklist onto a freshly provisioned home canvas.

    Creates the checklist component in the user's personal channel, queues its
    build, pre-ticks what the account already answers, and publishes the home
    layout with the component placed 2x5 in the top-left corner. The placement
    goes live before the build finishes — the tile shows a spinner until the
    artifact lands, which beats opening onto an empty grid. Raises on failure;
    the caller treats seeding as best-effort.
    """
    component = Canvas.objects.create(
        team_id=canvas.team_id,
        channel_id=channel_id,
        name=WELCOME_COMPONENT_NAME,
        kind=Canvas.KIND_COMPONENT,
        description="Onboarding checklist walking a new user through their first steps in PostHog Desktop.",
        created_by=user,
    )
    build_service.publish_source_project(
        component,
        project=welcome_checklist_project(),
        prompt=WELCOME_COMPONENT_NAME,
        name=None,
        has_expected_version=False,
        expected_version_id=None,
        task_id=None,
        created_by=user,
    )
    CanvasState.objects.create(
        team_id=canvas.team_id,
        canvas=component,
        scope=CanvasState.SCOPE_USER,
        user=user,
        key=WELCOME_STATE_KEY,
        value={
            # They are reading the checklist inside the desktop app.
            "download-desktop": True,
            "connect-github": Integration.objects.filter(
                team_id=canvas.team_id, kind=Integration.IntegrationKind.GITHUB
            ).exists(),
        },
    )
    layout = default_layout()
    layout["placements"] = [
        {
            "id": "p-welcome",
            "status": "live",
            "x": 0,
            "y": 0,
            "w": 2,
            "h": 5,
            "component": str(component.id),
            "version": "latest",
            "prompt": WELCOME_COMPONENT_NAME,
        }
    ]
    build_service.publish_grid_layout(
        canvas,
        layout=layout,
        prompt=WELCOME_COMPONENT_NAME,
        has_expected_version=False,
        expected_version_id=None,
        task_id=None,
        created_by=user,
    )
