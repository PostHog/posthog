import {
  ArrowCounterClockwise,
  Microphone,
  Play,
  Scissors,
  StopCircle,
  Trash,
  UploadSimple,
} from "@phosphor-icons/react";
import {
  Button,
  Card,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldLabel,
  FieldLegend,
  FieldSet,
  Input,
  Text,
} from "@posthog/quill";
import { MAX_CUSTOM_SOUND_SECONDS } from "@posthog/ui/utils/customSound";
import { useRef } from "react";
import { useCustomSoundCapture } from "./useCustomSoundCapture";

export function AddCustomSoundDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const sound = useCustomSoundCapture(onOpenChange);
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <Dialog open={open} onOpenChange={sound.handleOpenChange}>
      <DialogContent className="max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Add custom sound</DialogTitle>
          <DialogDescription>
            Record a clip or import an audio file, then give it a name. Clips
            must be {MAX_CUSTOM_SOUND_SECONDS}s or shorter.
          </DialogDescription>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-4">
          <Field>
            <FieldLabel htmlFor="custom-sound-name">Name</FieldLabel>
            <Input
              id="custom-sound-name"
              value={sound.name}
              onChange={(event) => sound.setName(event.target.value)}
              placeholder="e.g. My ding"
              maxLength={60}
            />
          </Field>

          <FieldSet className="gap-2">
            <FieldLegend variant="label">Sound</FieldLegend>

            <div className="flex flex-wrap items-center gap-2">
              {sound.isRecording ? (
                <Button variant="destructive" onClick={sound.stopRecording}>
                  <StopCircle weight="fill" /> Stop ({sound.elapsedLabel})
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  onClick={sound.startRecording}
                  disabled={!sound.recordingSupported}
                  title={
                    sound.recordingSupported
                      ? undefined
                      : "Recording isn't available on this device"
                  }
                >
                  <Microphone /> Record
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={() => fileInputRef.current?.click()}
                disabled={sound.isRecording}
              >
                <UploadSimple /> Import file
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept="audio/*"
                hidden
                aria-label="Import audio file"
                onChange={(event) => {
                  void sound.importFile(event.target.files?.[0]);
                  // Allow re-selecting the same file after a rejection.
                  event.target.value = "";
                }}
              />
            </div>

            {sound.hasClip && (
              <Card className="p-3">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <Button
                      variant="secondary"
                      size="icon-xs"
                      onClick={sound.playPreview}
                      aria-label="Preview clip"
                    >
                      <Play weight="fill" />
                    </Button>
                    <Text size="sm" variant="muted">
                      {sound.isTrimmed ? "Trimmed" : "Clip ready"} ·{" "}
                      {sound.clipDurationLabel}
                    </Text>
                    <div className="flex-1" />
                    <Button
                      variant="link-muted"
                      size="icon-xs"
                      onClick={sound.discardClip}
                      aria-label="Discard clip"
                    >
                      <Trash />
                    </Button>
                  </div>

                  {sound.canOfferTrim && (
                    <Button
                      variant={sound.isTrimmed ? "link-muted" : "secondary"}
                      size="xs"
                      className="self-start"
                      onClick={sound.toggleTrim}
                    >
                      {sound.isTrimmed ? (
                        <>
                          <ArrowCounterClockwise /> Keep full clip
                        </>
                      ) : (
                        <>
                          <Scissors /> Trim silence
                        </>
                      )}
                    </Button>
                  )}
                </div>
              </Card>
            )}

            {sound.error && (
              <Text size="sm" variant="destructive">
                {sound.error}
              </Text>
            )}
          </FieldSet>
        </DialogBody>

        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            Cancel
          </DialogClose>
          <Button
            variant="primary"
            onClick={sound.save}
            disabled={!sound.canSave}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
