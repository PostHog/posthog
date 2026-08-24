import type { EvidencePreview } from "@posthog/api-client/evidence-previews";
import {
  getObjectKind,
  type ObjectTagRef,
  objectWebPath,
} from "@posthog/core/inbox/objectTags";
import { useQuery } from "@tanstack/react-query";
import {
  Bug,
  ChartLine,
  ChatCircleText,
  ClipboardText,
  CursorClick,
  Database,
  Flag,
  Flask,
  type Icon,
  Lightning,
  PlayCircle,
  Pulse,
  ShieldCheck,
  Sparkle,
  SquaresFour,
  User,
  UsersThree,
} from "phosphor-react-native";
import { createContext, type ReactNode, useContext, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import { getCloudUrlFromRegion, useAuthStore } from "@/features/auth";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { useThemeColors } from "@/lib/theme";

const KIND_ICONS: Record<string, Icon> = {
  insight: ChartLine,
  hogql: Database,
  dashboard: SquaresFour,
  error: Bug,
  replay: PlayCircle,
  flag: Flag,
  experiment: Flask,
  survey: ClipboardText,
  ticket: ChatCircleText,
  trace: Sparkle,
  eval: ShieldCheck,
  event: Lightning,
  cohort: UsersThree,
  action: CursorClick,
  person: User,
};

const ObjectTagContext = createContext<(tag: ObjectTagRef) => void>(() => {});

function useObjectPreviewUrl(kind: string, id: string): string | null {
  const cloudRegion = useAuthStore((state) => state.cloudRegion);
  const projectId = useAuthStore((state) => state.projectId);
  const path = objectWebPath(kind, id);
  if (!path || !cloudRegion || !projectId) return null;
  return `${getCloudUrlFromRegion(cloudRegion)}/project/${projectId}${path}`;
}

function ObjectPreviewSheet({
  tag,
  onClose,
}: {
  tag: ObjectTagRef;
  onClose: () => void;
}) {
  const themeColors = useThemeColors();
  const meta = getObjectKind(tag.kind);
  const KindIcon = KIND_ICONS[tag.kind] ?? Pulse;

  const { data, isLoading } = useQuery<EvidencePreview | null>({
    queryKey: ["evidence-preview", tag.kind, tag.id],
    staleTime: 5 * 60 * 1000,
    retry: 1,
    queryFn: () => getPostHogApiClient().getEvidencePreview(tag.kind, tag.id),
  });

  const url = useObjectPreviewUrl(tag.kind, data?.resolvedId ?? tag.id);

  return (
    <SheetContainer open onClose={onClose}>
      <View className="gap-3 px-5 pt-2">
        <View className="flex-row items-center gap-1.5">
          <KindIcon size={13} color={themeColors.gray[9]} />
          <Text className="font-mono text-[11px] text-gray-9 uppercase tracking-wide">
            {meta.kindLabel}
          </Text>
          <Text className="ml-auto text-[11px] text-gray-9">{meta.source}</Text>
        </View>

        {isLoading ? (
          <ActivityIndicator color={themeColors.gray[9]} />
        ) : (
          <View className="gap-2">
            <Text className="font-semibold text-[15px] text-gray-12 leading-snug">
              {data?.title ?? tag.label}
            </Text>
            {data?.detail && (
              <Text className="text-[12px] text-gray-10 leading-snug">
                {data.detail}
              </Text>
            )}
            {data?.facts && data.facts.length > 0 && (
              <View className="flex-row flex-wrap gap-1.5">
                {data.facts.map((fact) => (
                  <Text
                    key={fact}
                    className="rounded bg-gray-3 px-1.5 py-0.5 text-[11px] text-gray-11"
                  >
                    {fact}
                  </Text>
                ))}
              </View>
            )}
            {tag.kind === "hogql" && (
              <Text className="rounded bg-gray-3 p-2 font-mono text-[11px] text-gray-11 leading-4">
                {tag.id}
              </Text>
            )}
          </View>
        )}

        {url && (
          <Pressable
            onPress={() => openExternalUrl(url)}
            className="mt-1 self-start rounded-md bg-gray-3 px-3 py-1.5"
            accessibilityRole="button"
          >
            <Text className="text-[12px] text-accent-11">
              Open in PostHog ↗
            </Text>
          </Pressable>
        )}
      </View>
    </SheetContainer>
  );
}

/**
 * Holds the single preview sheet for a message. The sheet is a Modal, so it
 * cannot render from inside a chip (chips live inside a paragraph `Text`);
 * chips open it through context instead.
 */
export function ObjectTagPreviewProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [active, setActive] = useState<ObjectTagRef | null>(null);
  return (
    <ObjectTagContext.Provider value={setActive}>
      {children}
      {active && (
        <ObjectPreviewSheet tag={active} onClose={() => setActive(null)} />
      )}
    </ObjectTagContext.Provider>
  );
}

/**
 * Inline reference to a PostHog object in an agent message, authored as a
 * `<kind id="...">label</kind>` tag. Tapping opens a sheet that resolves the
 * object's live name and status. Previews fetch only on tap, so a message full
 * of references never fans out concurrent authenticated queries.
 */
export function ObjectTagChip({ tag }: { tag: ObjectTagRef }) {
  const openPreview = useContext(ObjectTagContext);
  const meta = getObjectKind(tag.kind);
  return (
    <Text
      onPress={() => openPreview(tag)}
      className="rounded-md bg-gray-3 px-1.5 py-0.5 text-[12px] text-gray-12"
      accessibilityRole="button"
      accessibilityLabel={`${meta.kindLabel}: ${tag.label}`}
    >
      {tag.label}
    </Text>
  );
}
