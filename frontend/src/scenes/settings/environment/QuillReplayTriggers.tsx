import { ReactNode } from 'react'

import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    Separator,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
} from '@posthog/quill'

import IngestionControls from 'lib/components/IngestionControls'
import { QuillMatchTypeSelect } from 'lib/components/IngestionControls/QuillMatchTypeSelect'
import { QuillTriggerGroupsEditor } from 'lib/components/IngestionControls/triggers/triggerGroups/QuillTriggerGroupsEditor'
import { ReplayPlatform, TRIGGER_GROUPS_MIN_SDK_VERSION } from 'scenes/settings/environment/replayTriggersLogic'

import { AccessControlResourceType } from '~/types'

import { QuillSince } from './QuillSince'

export function QuillReplayTriggers({
    matchType,
    onChangeMatchType,
    selectedPlatform,
    onSelectPlatform,
    isV2TriggersEnabled,
    shouldMinimizeLegacyConditions,
    sdkCompatibilityBanner,
    recordingExclusions,
    legacyRecordingConditions,
    summary,
    mobileTriggers,
}: {
    matchType: 'any' | 'all'
    onChangeMatchType: (value: 'any' | 'all') => void
    selectedPlatform: ReplayPlatform
    onSelectPlatform: (platform: ReplayPlatform) => void
    isV2TriggersEnabled: boolean
    shouldMinimizeLegacyConditions: boolean
    sdkCompatibilityBanner: ReactNode
    recordingExclusions: ReactNode
    legacyRecordingConditions: ReactNode
    summary: ReactNode
    mobileTriggers: ReactNode
}): JSX.Element {
    return (
        <IngestionControls
            logicKey="session-replay"
            resourceType={AccessControlResourceType.SessionRecording}
            matchType={matchType}
            onChangeMatchType={onChangeMatchType}
        >
            <Tabs value={selectedPlatform} onValueChange={(platform) => onSelectPlatform(platform as ReplayPlatform)}>
                <TabsList variant="line">
                    <TabsTrigger value="web">Web</TabsTrigger>
                    <TabsTrigger value="mobile">Mobile</TabsTrigger>
                </TabsList>
                <TabsContent value="web">
                    <div className="flex flex-col gap-4">
                        {isV2TriggersEnabled && (
                            <>
                                {sdkCompatibilityBanner}

                                <QuillTriggerGroupsEditor
                                    titleBadge={<QuillSince web={{ version: TRIGGER_GROUPS_MIN_SDK_VERSION }} />}
                                />
                            </>
                        )}

                        {recordingExclusions}

                        {isV2TriggersEnabled && (
                            <div className="flex flex-col gap-4 pt-2">
                                <Separator />
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    Legacy recording conditions
                                </Heading>
                            </div>
                        )}

                        {isV2TriggersEnabled && shouldMinimizeLegacyConditions ? (
                            <Accordion>
                                <AccordionItem value="legacy-recording-conditions">
                                    <AccordionTrigger>
                                        <Text size="xs" variant="muted" render={<span className="m-0 font-normal" />}>
                                            Hidden because your web SDKs (v{TRIGGER_GROUPS_MIN_SDK_VERSION}+) use
                                            trigger groups. Expand to configure fallbacks for older SDK versions.
                                        </Text>
                                    </AccordionTrigger>
                                    <AccordionContent>
                                        <div className="flex flex-col gap-4">{legacyRecordingConditions}</div>
                                    </AccordionContent>
                                </AccordionItem>
                            </Accordion>
                        ) : (
                            <>
                                {isV2TriggersEnabled && (
                                    <Item tone="warning" size="sm">
                                        <ItemContent>
                                            <ItemDescription>
                                                Used by SDK versions &lt; v{TRIGGER_GROUPS_MIN_SDK_VERSION} and as
                                                fallback for newer versions if trigger groups are not configured.
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                )}
                                {legacyRecordingConditions}
                            </>
                        )}
                    </div>
                </TabsContent>
                <TabsContent value="mobile">
                    <div className="flex flex-col gap-2">
                        <Item tone="info" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    Trigger groups aren't available on mobile yet. Mobile recording uses the settings
                                    below, which are shared with web. Changing a setting here also changes it on web.
                                </ItemDescription>
                            </ItemContent>
                        </Item>
                        {summary}
                        <QuillMatchTypeSelect
                            lockedToAllReason="Mobile only supports trigger matching of type 'all'."
                            titleBadge={<QuillSince web={{ version: '1.238.0' }} />}
                        />
                        {mobileTriggers}
                    </div>
                </TabsContent>
            </Tabs>
        </IngestionControls>
    )
}
