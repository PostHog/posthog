import {
  ArrowCounterClockwise,
  Microphone,
  Play,
  Scissors,
  StopCircle,
  Trash,
  UploadSimple,
} from "@phosphor-icons/react";
import { MAX_CUSTOM_SOUND_SECONDS } from "@posthog/ui/utils/customSound";
import {
  Button,
  Card,
  Dialog,
  Flex,
  IconButton,
  Text,
  TextField,
} from "@radix-ui/themes";
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
    <Dialog.Root open={open} onOpenChange={sound.handleOpenChange}>
      <Dialog.Content maxWidth="420px">
        <Dialog.Title>Add custom sound</Dialog.Title>
        <Dialog.Description size="2" color="gray" mb="4">
          Record a clip or import an audio file, then give it a name. Clips must
          be {MAX_CUSTOM_SOUND_SECONDS}s or shorter.
        </Dialog.Description>

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
                <Button color="red" onClick={sound.stopRecording}>
                  <StopCircle weight="fill" /> Stop ({sound.elapsedLabel})
                </Button>
              ) : (
                <Button
                  variant="soft"
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
                variant="soft"
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
                    <IconButton
                      variant="soft"
                      size="1"
                      onClick={sound.playPreview}
                      aria-label="Preview clip"
                    >
                      <Play weight="fill" />
                    </IconButton>
                    <Text size="2" color="gray">
                      {sound.isTrimmed ? "Trimmed" : "Clip ready"} ·{" "}
                      {sound.clipDurationLabel}
                    </Text>
                    <Flex flexGrow="1" />
                    <IconButton
                      variant="ghost"
                      color="gray"
                      size="1"
                      onClick={sound.discardClip}
                      aria-label="Discard clip"
                    >
                      <Trash />
                    </IconButton>
                  </Flex>

                  {sound.canOfferTrim && (
                    <Button
                      variant={sound.isTrimmed ? "ghost" : "soft"}
                      size="1"
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

        <Flex gap="3" mt="4" justify="end">
          <Dialog.Close>
            <Button variant="soft" color="gray">
              Cancel
            </Button>
          </Dialog.Close>
          <Button onClick={sound.save} disabled={!sound.canSave}>
            Save
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
