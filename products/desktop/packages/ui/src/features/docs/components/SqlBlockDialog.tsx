import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Textarea,
} from "@posthog/quill";
import { useState } from "react";

/** Puts a SQL query in a doc. The doc keeps the query text and runs it on render. */
export function SqlBlockDialog({
  open,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (block: { query: string; title: string }) => void;
}) {
  const [query, setQuery] = useState("");
  const [title, setTitle] = useState("");

  const confirm = () => {
    onConfirm({ query: query.trim(), title: title.trim() });
    setQuery("");
    setTitle("");
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add a SQL query</DialogTitle>
          <DialogDescription>
            The doc keeps the query, not the rows, so it runs again every time
            someone opens the page.
          </DialogDescription>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-3">
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Name this block"
          />
          <Textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="select count() from events where event = '$pageview'"
            rows={8}
            className="font-mono text-xs"
            autoFocus
          />
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={query.trim().length === 0}
            onClick={confirm}
          >
            Add
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
