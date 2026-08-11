import { Text } from "react-native";

interface FileRefChipProps {
  label: string;
  /** True when the path only exists on the machine the desktop app ran on. */
  fromDesktop: boolean;
}

/**
 * A file referenced by the desktop composer. Deliberately not tappable: the
 * path points at the desktop's filesystem, so there is nothing the phone can
 * open. Rendered as a plain <Text> so it can sit inline inside a markdown
 * paragraph — RN does not allow <View> children inside <Text>, which is also
 * why the desktop chip's icon is dropped here (same trade-off as GithubRefChip).
 */
export function FileRefChip({ label, fromDesktop }: FileRefChipProps) {
  return (
    <Text
      className="rounded-md bg-gray-3 px-1.5 py-0.5 font-mono text-[11px] text-gray-11"
      accessibilityLabel={
        fromDesktop ? `File from desktop ${label}` : `File ${label}`
      }
    >
      {label}
      {fromDesktop ? (
        <Text className="text-gray-9">{" · from desktop"}</Text>
      ) : null}
    </Text>
  );
}
