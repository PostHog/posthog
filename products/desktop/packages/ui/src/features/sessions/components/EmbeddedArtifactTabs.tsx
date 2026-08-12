import { X } from "@phosphor-icons/react";
import {
  ArtifactTabHostProvider,
  type ArtifactTarget,
} from "@posthog/ui/features/panels/useOpenArtifact";
import { type ReactNode, useCallback, useState } from "react";
import { ArtifactPreview } from "./ArtifactPreview";

// Hosts the artifact tabs for a session shown outside the task's own route,
// where the panel tab strip that would otherwise render them isn't mounted.
export function EmbeddedArtifactTabs({
  taskId,
  children,
}: {
  taskId: string;
  children: ReactNode;
}) {
  const [tabs, setTabs] = useState<ArtifactTarget[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  const open = useCallback((artifact: ArtifactTarget) => {
    setTabs((current) =>
      current.some((tab) => tab.artifactId === artifact.artifactId)
        ? current
        : [...current, artifact],
    );
    setActiveId(artifact.artifactId);
  }, []);

  const close = useCallback((artifactId: string) => {
    setTabs((current) =>
      current.filter((tab) => tab.artifactId !== artifactId),
    );
    setActiveId((active) => (active === artifactId ? null : active));
  }, []);

  const active = tabs.find((tab) => tab.artifactId === activeId) ?? null;

  return (
    <ArtifactTabHostProvider open={open}>
      <div className="flex h-full min-h-0 flex-col">
        {tabs.length > 0 && (
          <div className="flex shrink-0 items-center gap-1 overflow-hidden border-gray-6 border-b px-1 py-1">
            <TabPill
              label="Chat"
              active={!active}
              onSelect={() => setActiveId(null)}
            />
            {tabs.map((tab) => (
              <TabPill
                key={tab.artifactId}
                label={tab.name}
                active={tab.artifactId === active?.artifactId}
                onSelect={() => setActiveId(tab.artifactId)}
                onClose={() => close(tab.artifactId)}
              />
            ))}
          </div>
        )}
        {/* An artifact covers the session rather than replacing it, so the
            thread keeps its box and its virtualized rows their measurements. */}
        <div className="relative flex min-h-0 flex-1 flex-col">
          {children}
          {active && (
            <div className="absolute inset-0 flex flex-col bg-background">
              <ArtifactPreview
                taskId={taskId}
                runId={active.runId}
                artifactId={active.artifactId}
                name={active.name}
              />
            </div>
          )}
        </div>
      </div>
    </ArtifactTabHostProvider>
  );
}

// A plain button rather than a quill TabsTrigger: the close affordance would
// nest a button inside it.
function TabPill({
  label,
  active,
  onSelect,
  onClose,
}: {
  label: string;
  active: boolean;
  onSelect: () => void;
  onClose?: () => void;
}) {
  return (
    <div className="flex min-w-0 items-center">
      <button
        type="button"
        onClick={onSelect}
        title={label}
        className={`max-w-[160px] truncate rounded px-1.5 py-0.5 text-[12px] transition-colors ${
          active ? "bg-gray-4 text-gray-12" : "text-gray-10 hover:bg-gray-3"
        }`}
      >
        {label}
      </button>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${label}`}
          className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
        >
          <X size={10} />
        </button>
      )}
    </div>
  );
}
