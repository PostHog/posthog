import type { RpcExtensionUIResponse } from "@posthog/agent/pi/types";
import type { PiExtensionDialogRequest } from "@posthog/core/pi-runtime/piExtensionStore";
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
  Label,
  Textarea,
} from "@posthog/quill";
import { type FormEvent, useId, useRef, useState } from "react";
import { buildPiExtensionResponse } from "./piExtensionResponse";

interface PiExtensionDialogProps {
  request: PiExtensionDialogRequest;
  onRespond: (response: RpcExtensionUIResponse) => Promise<void>;
  onCancel: () => Promise<void>;
}

export function PiExtensionDialog({
  request,
  onRespond,
  onCancel,
}: PiExtensionDialogProps) {
  const [value, setValue] = useState(
    request.method === "editor" ? (request.prefill ?? "") : "",
  );
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const fieldId = useId();

  const complete = async (response?: RpcExtensionUIResponse): Promise<void> => {
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    try {
      if (response) {
        await onRespond(response);
      } else {
        await onCancel();
      }
    } catch {
      // The controller retains the dialog and reports delivery failures by toast.
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (request.method === "select") {
      return;
    }
    void complete(
      buildPiExtensionResponse(
        request,
        request.method === "confirm" ? true : value,
      ),
    );
  };

  const description =
    request.method === "select"
      ? "Choose one of the available options."
      : request.method === "confirm"
        ? request.message
        : request.method === "editor"
          ? "Enter or edit the response."
          : "Enter a response.";

  return (
    <Dialog open onOpenChange={(open) => !open && void complete()}>
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-lg"
        aria-busy={submitting}
      >
        <form aria-label={`${request.title} response`} onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{request.title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <DialogBody viewportClassName="max-h-80">
            {request.method === "select" ? (
              <div className="flex flex-col gap-2">
                {request.options.map((option) => (
                  <Button
                    key={option}
                    disabled={submitting}
                    type="button"
                    variant="outline"
                    onClick={() =>
                      void complete(buildPiExtensionResponse(request, option))
                    }
                  >
                    {option}
                  </Button>
                ))}
              </div>
            ) : request.method === "confirm" ? null : (
              <div className="flex flex-col gap-2">
                <Label htmlFor={fieldId}>Response</Label>
                {request.method === "editor" ? (
                  <Textarea
                    autoFocus
                    id={fieldId}
                    className="min-h-48 resize-y"
                    disabled={submitting}
                    value={value}
                    onChange={(event) => setValue(event.target.value)}
                  />
                ) : (
                  <Input
                    autoFocus
                    id={fieldId}
                    disabled={submitting}
                    value={value}
                    placeholder={request.placeholder}
                    onChange={(event) => setValue(event.target.value)}
                  />
                )}
              </div>
            )}
          </DialogBody>
          <DialogFooter>
            <Button
              disabled={submitting}
              type="button"
              variant="outline"
              onClick={() => void complete()}
            >
              Cancel
            </Button>
            {request.method === "confirm" && (
              <Button
                disabled={submitting}
                type="button"
                variant="outline"
                onClick={() =>
                  void complete(buildPiExtensionResponse(request, false))
                }
              >
                Decline
              </Button>
            )}
            {request.method !== "select" && (
              <Button disabled={submitting} type="submit" variant="primary">
                {submitting
                  ? "Submitting…"
                  : request.method === "confirm"
                    ? "Confirm"
                    : "Submit"}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
