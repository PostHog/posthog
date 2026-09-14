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
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { MAX_CUSTOM_SOUND_SECONDS } from "@posthog/ui/utils/customSound";
import { Card, Flex, Text, TextField } from "@radix-ui/themes";
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

        <Flex direction="column" gap="4">
          <Flex direction="column" gap="1">
            <Text
              as="label"
              htmlFor="custom-sound-name"
              size="2"
              weight="medium"
            >
              Name
            </Text>
            <TextField.Root
              id="custom-sound-name"
              value={sound.name}
              onChange={(event) => sound.setName(event.target.value)}
              placeholder="e.g. My ding"
              maxLength={60}
            />
          </Flex>

          <Flex direction="column" gap="2">
            <Text as="div" size="2" weight="medium">
              Sound
            </Text>

            <Flex gap="2" align="center" wrap="wrap">
              {sound.isRecording ? (
                <Button variant="destructive" onClick={sound.stopRecording}>
                  <StopCircle weight="fill" /> Stop ({sound.elapsedLabel})
                </Button>
              ) : (
                <Button
                  variant="outline"
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
                variant="outline"
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
            </Flex>

            {sound.hasClip && (
              <Card size="1">
                <Flex direction="column" gap="2">
                  <Flex align="center" gap="2">
                    <Button
                      variant="outline"
                      size="icon-sm"
                      onClick={sound.playPreview}
                      aria-label="Preview clip"
                    >
                      <Play weight="fill" />
                    </Button>
                    <Text size="2" color="gray">
                      {sound.isTrimmed ? "Trimmed" : "Clip ready"} ·{" "}
                      {sound.clipDurationLabel}
                    </Text>
                    <Flex flexGrow="1" />
                    <Button
                      variant="default"
                      size="icon-sm"
                      onClick={sound.discardClip}
                      aria-label="Discard clip"
                    >
                      <Trash />
                    </Button>
                  </Flex>

                  {sound.canOfferTrim && (
                    <Button
                      variant={sound.isTrimmed ? "default" : "outline"}
                      size="sm"
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
                </Flex>
              </Card>
            )}

            {sound.error && (
              <Text size="2" color="red">
                {sound.error}
              </Text>
            )}
          </Flex>
        </Flex>

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
