import { useHostTRPC } from "@posthog/host-router/react";
import { CopyableCommand } from "@posthog/ui/features/settings/components/CopyableCommand";
import { useQuery } from "@tanstack/react-query";
import type { ReactElement } from "react";

function PermissionBadge({
  permission,
  color,
}: {
  permission: string;
  color: "green" | "red";
}) {
  const bgClass = color === "green" ? "bg-green-500/20" : "bg-red-500/20";
  const textClass = color === "green" ? "text-green-400" : "text-red-400";
  const borderClass =
    color === "green" ? "border-green-500/30" : "border-red-500/30";

  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-[12px] ${bgClass} ${textClass} ${borderClass}`}
    >
      {permission}
    </span>
  );
}

function PermissionList({
  title,
  permissions,
  color,
}: {
  title: string;
  permissions: string[];
  color: "green" | "red";
}) {
  return (
    <>
      <span className="pt-0.5 text-muted-foreground text-xs">{title}</span>
      {permissions.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {permissions.map((perm) => (
            <PermissionBadge key={perm} permission={perm} color={color} />
          ))}
        </div>
      ) : (
        <span className="pt-0.5 text-muted-foreground text-xs">None</span>
      )}
    </>
  );
}

export function PermissionsSettings(): ReactElement {
  const trpc = useHostTRPC();
  const { data } = useQuery(trpc.os.getClaudePermissions.queryOptions());

  return (
    <div className="flex flex-col gap-3 px-3.5 py-3">
      <div className="flex items-start justify-between gap-6">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="font-medium text-[13px] text-foreground leading-snug">
            Claude permission rules
          </span>
          <span className="text-[12px] text-muted-foreground leading-snug">
            Tool permissions from your Claude settings. Allowed tools run
            without prompting. Denied tools are always blocked. Codex keeps its
            own rules in config.toml
          </span>
        </div>
        <CopyableCommand command="claude config" />
      </div>
      <div className="grid grid-cols-[4rem_1fr] items-start gap-x-3 gap-y-2">
        <PermissionList
          title="Allowed"
          permissions={data?.allow ?? []}
          color="green"
        />
        <PermissionList
          title="Denied"
          permissions={data?.deny ?? []}
          color="red"
        />
      </div>
    </div>
  );
}
