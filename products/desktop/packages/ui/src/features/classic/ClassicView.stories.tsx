import { SidebarSimpleIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { visibleRailDestinations } from "@posthog/ui/features/canvas/components/railDestinations";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { type ReactElement, useEffect, useState } from "react";
import { ClassicSidebar } from "./ClassicSidebar";
import { ClassicContent } from "./ClassicView";
import type { ClassicFrameProps } from "./classicFrameHost";

const dashboardFixture = `<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
  *{box-sizing:border-box}body{margin:0;padding:24px;font:14px system-ui;background:#f6f5f2;color:#252525}
  h1{font-size:24px;margin:12px 0}h2{font-size:14px;margin:0 0 24px}.muted{color:#666;font-size:12px}
  .filters{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}.filter{border:1px solid #d6d5d2;background:white;border-radius:5px;padding:8px 12px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.card{background:white;border:1px solid #d6d5d2;border-radius:7px;padding:20px}
  .metric{font-size:32px;font-weight:600;margin-bottom:20px}svg{width:100%;height:140px}.bar{height:26px;background:#4b67db;margin:16px 0;border-radius:3px}
  </style></head><body><div class="muted">Dashboard fixture · preview only</div><h1>Product overview</h1>
  <p class="muted">An example of the web dashboard body inside the desktop shell.</p>
  <div class="filters"><span class="filter">Last 7 days</span><span class="filter">Add filter</span><span class="filter">Refresh</span></div>
  <div class="grid"><section class="card"><h2>Active users</h2><div class="metric">1,248</div>
  <svg viewBox="0 0 400 140" role="img" aria-label="Sample active users trend"><path d="M0 120 L400 120 M0 70 L400 70 M0 20 L400 20" fill="none" stroke="#eee"/><path d="M0 110 L65 90 L130 95 L195 45 L260 60 L325 30 L400 15" fill="none" stroke="#4b67db" stroke-width="3"/></svg>
  <div class="muted">Mon　　Tue　　Wed　　Thu　　Fri　　Sat　　Sun</div></section>
  <section class="card"><h2>Activation funnel</h2><div class="metric">64%</div><div class="muted">Signed up</div><div class="bar"></div><div class="muted">Created a project</div><div class="bar" style="width:82%"></div><div class="muted">Viewed a dashboard</div><div class="bar" style="width:64%"></div></section></div></body></html>`;

function DashboardFixture({ onStatusChange }: ClassicFrameProps): ReactElement {
  return (
    <iframe
      title="Sample dashboard fixture"
      sandbox=""
      srcDoc={dashboardFixture}
      onLoad={() => onStatusChange("ready")}
      className="size-full border-0"
    />
  );
}

function FailedFrame({ onStatusChange }: ClassicFrameProps): null {
  useEffect(() => onStatusChange("error"), [onStatusChange]);
  return null;
}

function ClassicPreview({
  before = false,
  failed = false,
}: {
  before?: boolean;
  failed?: boolean;
}): ReactElement {
  const [expanded, setExpanded] = useState(true);
  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <ChromeBar inset="control">
        <Button
          size="icon"
          aria-label="Toggle sidebar"
          onClick={() => setExpanded(!expanded)}
        >
          <SidebarSimpleIcon />
        </Button>
        <span className="text-xs">PostHog Desktop</span>
      </ChromeBar>
      <div className="flex min-h-0 flex-1">
        <div className="flex w-11 shrink-0 flex-col items-center gap-2 border-border border-r py-3">
          {visibleRailDestinations({
            home: true,
            inbox: true,
            loops: true,
            context: true,
            classic: true,
            savedSearches: false,
          })
            .filter((item) =>
              [
                "home",
                "spaces",
                "loops",
                "context",
                ...(before ? [] : ["classic"]),
              ].includes(item.pane),
            )
            .map(({ pane, label, Icon }) => (
              <Button
                key={pane}
                size="icon"
                aria-label={label}
                data-selected={pane === "classic" || undefined}
                className="data-selected:bg-fill-selected data-selected:text-foreground"
              >
                <Icon size={18} />
              </Button>
            ))}
        </div>
        {!before && expanded && (
          <div className="flex w-60 shrink-0 border-border border-r">
            <ClassicSidebar />
          </div>
        )}
        <div className="min-w-0 flex-1">
          {before ? (
            <div className="p-6 text-muted-foreground text-xs">
              No Classic destination
            </div>
          ) : (
            <ClassicContent
              Frame={failed ? FailedFrame : DashboardFixture}
              url="https://us.posthog.com/project/1/dashboard"
              accountId="example-account"
            />
          )}
        </div>
      </div>
    </div>
  );
}

const meta = {
  title: "Classic/Preview",
  component: ClassicPreview,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ClassicPreview>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Dashboard: Story = {};
export const Before: Story = { args: { before: true } };
export const LoadFailure: Story = { args: { failed: true } };
