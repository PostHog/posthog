import { searchInsightsForDoc } from "@posthog/api-client/docs";
import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Spinner,
  Text,
} from "@posthog/quill";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useDocsClient } from "../hooks/useDocsClient";

export interface PickedInsight {
  shortId: string;
  label: string;
}

/**
 * Picks one or more saved insights to put in a doc. The doc keeps the reference,
 * so the chart shows what the insight shows today, not what it showed when it
 * was added.
 */
export function InsightPickerDialog({
  open,
  onOpenChange,
  multiple,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  multiple?: boolean;
  onConfirm: (insights: PickedInsight[]) => void;
}) {
  const docsClient = useDocsClient();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<PickedInsight[]>([]);

  const { data, isLoading } = useQuery({
    queryKey: ["docs", "insight-search", docsClient?.projectId ?? null, search],
    queryFn: async () => {
      if (!docsClient) return [];
      return searchInsightsForDoc(
        docsClient.client,
        docsClient.projectId,
        search,
      );
    },
    enabled: open && !!docsClient,
    staleTime: 30_000,
  });

  const toggle = (insight: PickedInsight) => {
    if (!multiple) {
      setPicked([insight]);
      return;
    }
    setPicked((current) =>
      current.some((entry) => entry.shortId === insight.shortId)
        ? current.filter((entry) => entry.shortId !== insight.shortId)
        : [...current, insight],
    );
  };

  const confirm = () => {
    onConfirm(picked);
    setPicked([]);
    setSearch("");
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {multiple ? "Pick the numbers" : "Pick an insight"}
          </DialogTitle>
          <DialogDescription>
            The doc keeps a link to the insight, so the chart stays current.
          </DialogDescription>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-3">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search insights"
            autoFocus
          />
          {isLoading ? (
            <div className="flex justify-center py-6">
              <Spinner />
            </div>
          ) : (data ?? []).length === 0 ? (
            <Text size="sm" className="py-6 text-center text-(--gray-11)">
              No insights match that. Try another word.
            </Text>
          ) : (
            <ul className="flex flex-col gap-1">
              {(data ?? []).map((insight) => {
                const label =
                  insight.name || insight.derived_name || insight.short_id;
                const isPicked = picked.some(
                  (entry) => entry.shortId === insight.short_id,
                );
                return (
                  <li key={insight.short_id}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded-(--radius-2) px-2 py-1.5 text-left hover:bg-(--gray-3)"
                      onClick={() =>
                        toggle({ shortId: insight.short_id, label })
                      }
                    >
                      {multiple ? <Checkbox checked={isPicked} /> : null}
                      <span className="truncate">{label}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={picked.length === 0}
            onClick={confirm}
          >
            Add
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
