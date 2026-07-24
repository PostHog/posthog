import { CaretDown, CaretRight } from "@phosphor-icons/react";
import type {
  McpApprovalState,
  McpInstallationTool,
} from "@posthog/api-client/posthog-client";
import { Badge, Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import { ToolPolicyToggle } from "./ToolPolicyToggle";

interface ToolRowProps {
  tool: McpInstallationTool;
  onChange: (approval_state: McpApprovalState) => void;
}

export function ToolRow({ tool, onChange }: ToolRowProps) {
  const [open, setOpen] = useState(false);
  const hasDescription = !!tool.description?.trim();
  const removed = !!tool.removed_at;

  return (
    <div className={`rounded border border-border bg-gray-1 transition-colors`}>
      <div className="flex w-full min-w-0 items-center gap-3 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
          aria-expanded={open}
        >
          {open ? (
            <CaretDown
              size={12}
              weight="bold"
              className="shrink-0 text-gray-10"
            />
          ) : (
            <CaretRight
              size={12}
              weight="bold"
              className="shrink-0 text-gray-10"
            />
          )}
          <div className="flex min-w-0 flex-1 flex-col">
            <Flex align="center" gap="2" minWidth="0">
              <Text
                truncate
                className="select-text font-medium text-sm"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}
              >
                {tool.tool_name}
              </Text>
              {removed && (
                <Badge color="gray" variant="soft" size="1">
                  Removed
                </Badge>
              )}
            </Flex>
            <Text
              color="gray"
              truncate
              style={{ fontStyle: hasDescription ? undefined : "italic" }}
              className="text-[13px]"
            >
              {hasDescription ? tool.description : "No description provided"}
            </Text>
          </div>
        </button>
        <div className="shrink-0">
          <ToolPolicyToggle
            value={tool.approval_state ?? "needs_approval"}
            onChange={onChange}
            disabled={removed}
          />
        </div>
      </div>
      {open && (
        <div className="border-gray-5 border-t bg-gray-2 px-3 py-3">
          <Flex direction="column" gap="3">
            <Flex direction="column" gap="1">
              <Text color="gray" className="font-medium text-[13px]">
                Description
              </Text>
              <Text className="text-sm">
                {hasDescription ? tool.description : "No description provided."}
              </Text>
            </Flex>
            <Flex direction="column" gap="1">
              <Text color="gray" className="font-medium text-[13px]">
                Input schema
              </Text>
              <pre className="overflow-x-auto rounded bg-gray-3 p-2 text-xs">
                {JSON.stringify(tool.input_schema ?? {}, null, 2)}
              </pre>
            </Flex>
          </Flex>
        </div>
      )}
    </div>
  );
}
