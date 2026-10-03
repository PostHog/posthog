import { useHostTRPC } from "@posthog/host-router/react";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { useQuery } from "@tanstack/react-query";

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
  description,
  permissions,
  color,
  emptyMessage,
}: {
  title: string;
  description: string;
  permissions: string[];
  color: "green" | "red";
  emptyMessage: string;
}) {
  return (
    <SettingsCardRow label={title} description={description} stacked>
      {permissions.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {permissions.map((perm) => (
            <PermissionBadge key={perm} permission={perm} color={color} />
          ))}
        </div>
      ) : (
        <span className="text-[12px] text-muted-foreground">
          {emptyMessage}
        </span>
      )}
    </SettingsCardRow>
  );
}

export function PermissionsSettings() {
  const trpc = useHostTRPC();
  const { data } = useQuery(trpc.os.getClaudePermissions.queryOptions());

  return (
    <>
      <PermissionList
        title="Allowed"
        description="Tools that run without asking"
        permissions={data?.allow ?? []}
        color="green"
        emptyMessage="No allowed permissions configured"
      />
      <PermissionList
        title="Denied"
        description="Tools that are always blocked"
        permissions={data?.deny ?? []}
        color="red"
        emptyMessage="No denied permissions configured"
      />
    </>
  );
}
