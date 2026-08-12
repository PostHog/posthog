import { useHostTRPC } from "@posthog/host-router/react";
import { Box, Flex, Text } from "@radix-ui/themes";
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
  permissions,
  color,
  emptyMessage,
}: {
  title: string;
  permissions: string[];
  color: "green" | "red";
  emptyMessage: string;
}) {
  return (
    <Box className="rounded-lg border border-gray-6 bg-gray-2 p-3">
      <Text className="mb-2 block font-medium text-[13px]">{title}</Text>
      <Box className="min-h-[40px] rounded border border-gray-5 bg-gray-3 p-2.5">
        {permissions.length > 0 ? (
          <Flex wrap="wrap" gap="2">
            {permissions.map((perm) => (
              <PermissionBadge key={perm} permission={perm} color={color} />
            ))}
          </Flex>
        ) : (
          <Text color="gray" className="text-[13px]">
            {emptyMessage}
          </Text>
        )}
      </Box>
    </Box>
  );
}

export function PermissionsSettings() {
  const trpc = useHostTRPC();
  const { data } = useQuery(trpc.os.getClaudePermissions.queryOptions());

  return (
    <Flex direction="column" gap="3" mb="2">
      <PermissionList
        title="Allowed"
        permissions={data?.allow ?? []}
        color="green"
        emptyMessage="No allowed permissions configured"
      />

      <PermissionList
        title="Denied"
        permissions={data?.deny ?? []}
        color="red"
        emptyMessage="No denied permissions configured"
      />
    </Flex>
  );
}
