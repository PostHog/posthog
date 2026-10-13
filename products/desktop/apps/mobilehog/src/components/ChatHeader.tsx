import { Button, Host, Image, Menu } from "@expo/ui/swift-ui";
import { frame } from "@expo/ui/swift-ui/modifiers";
import { isSafeGitHubPullRequestUrl } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useNavigation, useRouter } from "expo-router";
import { Linking, Pressable, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass, GlassCircleButton } from "@/components/Glass";
import { MenuIcon } from "@/components/Icons";
import { useTaskActions } from "@/components/TaskRow";
import { colors } from "@/lib/theme";

const BUTTON = 46;

interface ChatHeaderProps {
  showNewChat?: boolean;
  // The open chat's task, for the options menu beside new chat.
  task?: Task;
}

export function ChatHeader({ showNewChat = true, task }: ChatHeaderProps) {
  const navigation = useNavigation<{ openDrawer: () => void }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { rename, setArchived } = useTaskActions(task);
  const prUrl = task?.latest_run?.output?.pr_url;
  const safePrUrl =
    typeof prUrl === "string" && isSafeGitHubPullRequestUrl(prUrl)
      ? prUrl
      : null;
  return (
    <View
      style={[styles.root, { paddingTop: insets.top + 6 }]}
      pointerEvents="box-none"
    >
      <GlassCircleButton onPress={() => navigation.openDrawer()}>
        <MenuIcon />
      </GlassCircleButton>
      <View style={{ flex: 1 }} pointerEvents="none" />
      {showNewChat ? (
        <Glass interactive style={styles.pair}>
          <Pressable
            onPress={() => router.replace("/(drawer)")}
            hitSlop={8}
            style={({ pressed }) => [
              styles.pairButton,
              pressed && { opacity: 0.6 },
            ]}
          >
            <Host matchContents>
              <Image
                systemName="square.and.pencil"
                size={18}
                color={colors.ink}
              />
            </Host>
          </Pressable>
          {task ? (
            <>
              <View style={styles.divider} />
              <Host matchContents>
                <Menu
                  label={
                    <Image systemName="ellipsis" size={18} color={colors.ink} />
                  }
                  modifiers={[frame({ width: BUTTON, height: BUTTON })]}
                >
                  {safePrUrl ? (
                    <Button
                      label="Open pull request"
                      systemImage="arrow.triangle.pull"
                      onPress={() => Linking.openURL(safePrUrl).catch(() => {})}
                    />
                  ) : null}
                  <Button
                    label="Rename"
                    systemImage="pencil"
                    onPress={rename}
                  />
                  <Button
                    label="Archive"
                    systemImage="archivebox"
                    onPress={() =>
                      setArchived(true, () => router.replace("/(drawer)"))
                    }
                  />
                </Menu>
              </Host>
            </>
          ) : null}
        </Glass>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    zIndex: 10,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
  },
  pair: {
    height: BUTTON,
    borderRadius: BUTTON / 2,
    flexDirection: "row",
    alignItems: "center",
    overflow: "hidden",
  },
  pairButton: {
    width: BUTTON,
    height: BUTTON,
    alignItems: "center",
    justifyContent: "center",
  },
  divider: {
    width: StyleSheet.hairlineWidth,
    height: 20,
    backgroundColor: colors.line,
  },
});
