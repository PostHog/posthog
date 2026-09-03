import { JSONContent } from '@tiptap/core'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonColorPicker,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    Link,
} from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { SupportEditor, serializeToPlainText } from '../../components/Editor'
import { supportSettingsLogic } from './supportSettingsLogic'

/** Wrap plain greeting text in a TipTap doc so the rich editor can seed from a team that has no rich greeting yet. */
function greetingTextToRichContent(text: string): JSONContent {
    return {
        type: 'doc',
        content: [{ type: 'paragraph', content: text ? [{ type: 'text', text }] : [] }],
    }
}

/**
 * A greeting is blank when it has no visible text. TipTap's own emptiness check counts a lone space
 * or hard break as content, which would leave Save enabled for a greeting that publishes nothing, so
 * match the saver and judge emptiness by the plain-text fallback instead.
 */
function isGreetingBlank(editor: RichContentEditorType | null): boolean {
    return !editor || !serializeToPlainText(editor.getJSON())
}

export function WidgetSection(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const {
        generateNewToken,
        setWidgetEnabledLoading,
        setGreetingIsEmpty,
        saveGreetingText,
        setIdentificationFormTitleValue,
        saveIdentificationFormTitle,
        setIdentificationFormDescriptionValue,
        saveIdentificationFormDescription,
        setPlaceholderTextValue,
        savePlaceholderText,
    } = useActions(supportSettingsLogic)
    const {
        widgetEnabledLoading,
        greetingIsEmpty,
        identificationFormTitleValue,
        identificationFormDescriptionValue,
        placeholderTextValue,
    } = useValues(supportSettingsLogic)

    const greetingEditorRef = useRef<RichContentEditorType | null>(null)

    return (
        <SceneSection
            title="In-app widget"
            description={
                <>
                    Add a chat widget to your website for customers to reach you.{' '}
                    <Link to="https://posthog.com/docs/support/widget" target="_blank">
                        Docs
                    </Link>
                    . For logged-in users, use{' '}
                    <Link
                        to="https://posthog.com/docs/support/javascript-api#user-identification"
                        target="_blank"
                        targetBlankIcon
                    >
                        identity verification
                    </Link>{' '}
                    so tickets persist across browsers and devices.
                </>
            }
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label className="w-40 shrink-0 font-medium">Enable in-app widget</label>
                        <p className="text-xs text-muted-alt">
                            Turn on the in-app support widget to start receiving messages from your users
                        </p>
                    </div>
                    <LemonSwitch
                        checked={!!currentTeam?.conversations_settings?.widget_enabled}
                        onChange={(checked) => {
                            setWidgetEnabledLoading(true)
                            updateCurrentTeam({
                                conversations_settings: {
                                    ...currentTeam?.conversations_settings,
                                    widget_enabled: checked,
                                },
                            })
                        }}
                        loading={widgetEnabledLoading}
                    />
                </div>

                {currentTeam?.conversations_settings?.widget_enabled && (
                    <>
                        <LemonDivider />
                        <LemonBanner type="info" className="my-2">
                            Allowed domains for the widget are managed under the <strong>Direct API</strong> section —
                            they apply to both the widget and direct API calls.
                        </LemonBanner>
                        <SceneSection title="Visual settings" className="mt-8" titleSize="sm">
                            <LemonCard hoverEffect={false} className="px-4 py-3">
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Button color</label>
                                    <LemonColorPicker
                                        colors={[
                                            '#1d4aff',
                                            '#00aaff',
                                            '#00cc44',
                                            '#ffaa00',
                                            '#ff4444',
                                            '#9b59b6',
                                            '#1abc9c',
                                            '#000000',
                                        ]}
                                        selectedColor={currentTeam?.conversations_settings?.widget_color || '#1d4aff'}
                                        onSelectColor={(color) => {
                                            updateCurrentTeam({
                                                conversations_settings: {
                                                    ...currentTeam?.conversations_settings,
                                                    widget_color: color,
                                                },
                                            })
                                        }}
                                        showCustomColor
                                    />
                                </div>
                                <LemonDivider />
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Widget position</label>
                                    <LemonSelect
                                        value={currentTeam?.conversations_settings?.widget_position || 'bottom_right'}
                                        onChange={(value) => {
                                            updateCurrentTeam({
                                                conversations_settings: {
                                                    ...currentTeam?.conversations_settings,
                                                    widget_position: value,
                                                },
                                            })
                                        }}
                                        options={[
                                            { value: 'bottom_right', label: 'Bottom right' },
                                            { value: 'bottom_left', label: 'Bottom left' },
                                            { value: 'top_right', label: 'Top right' },
                                            { value: 'top_left', label: 'Top left' },
                                        ]}
                                    />
                                </div>
                                <LemonDivider />
                                <div className="flex flex-col gap-2 py-2">
                                    <div>
                                        <label className="font-medium">Greeting message</label>
                                        <p className="text-xs text-muted-alt mb-2">
                                            Shown when the widget opens. Add a link to point visitors to your FAQ or
                                            docs.
                                        </p>
                                    </div>
                                    {currentTeam && (
                                        <SupportEditor
                                            key={currentTeam.id}
                                            placeholder="Enter greeting message"
                                            disableMentions
                                            initialContent={
                                                currentTeam.conversations_settings?.widget_greeting_rich_content ??
                                                greetingTextToRichContent(
                                                    currentTeam.conversations_settings?.widget_greeting_text ??
                                                        'Hey, how can I help you today?'
                                                )
                                            }
                                            onCreate={(editor) => {
                                                greetingEditorRef.current = editor
                                                setGreetingIsEmpty(isGreetingBlank(editor))
                                            }}
                                            onUpdate={() =>
                                                setGreetingIsEmpty(isGreetingBlank(greetingEditorRef.current))
                                            }
                                        />
                                    )}
                                    <div className="flex justify-end">
                                        <LemonButton
                                            type="primary"
                                            onClick={() =>
                                                saveGreetingText(greetingEditorRef.current?.getJSON() ?? null)
                                            }
                                            loading={currentTeamLoading}
                                            disabledReason={greetingIsEmpty ? 'Enter a greeting message' : undefined}
                                        >
                                            Save
                                        </LemonButton>
                                    </div>
                                </div>
                                <LemonDivider />
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Placeholder text</label>
                                    <div className="flex gap-2 flex-1">
                                        <LemonInput
                                            value={
                                                placeholderTextValue ??
                                                currentTeam?.conversations_settings?.widget_placeholder_text ??
                                                'Type your message...'
                                            }
                                            placeholder="Enter placeholder text"
                                            onChange={setPlaceholderTextValue}
                                            fullWidth
                                        />
                                        <LemonButton
                                            type="primary"
                                            onClick={savePlaceholderText}
                                            disabledReason={
                                                !placeholderTextValue ? 'Enter placeholder text' : undefined
                                            }
                                        >
                                            Save
                                        </LemonButton>
                                    </div>
                                </div>
                            </LemonCard>
                        </SceneSection>
                        <SceneSection title="Identification form" className="mt-8" titleSize="sm">
                            <LemonCard hoverEffect={false} className="px-4 py-3">
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <div>
                                        <label className="w-40 shrink-0 font-medium">Require email</label>
                                        <p className="text-xs text-muted-alt mb-2">
                                            Require user to enter their email address to start the chat.
                                        </p>
                                    </div>
                                    <LemonSwitch
                                        checked={!!currentTeam?.conversations_settings?.widget_require_email}
                                        onChange={(checked) => {
                                            updateCurrentTeam({
                                                conversations_settings: {
                                                    ...currentTeam?.conversations_settings,
                                                    widget_require_email: checked,
                                                },
                                            })
                                        }}
                                    />
                                </div>

                                {currentTeam?.conversations_settings?.widget_require_email && (
                                    <>
                                        <LemonDivider />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <div>
                                                <label className="w-40 shrink-0 font-medium">Collect name</label>
                                                <p className="text-xs text-muted-alt mb-2">
                                                    Collect user's name to personalize the chat.
                                                </p>
                                            </div>
                                            <LemonSwitch
                                                checked={!!currentTeam?.conversations_settings?.widget_collect_name}
                                                onChange={(checked) => {
                                                    updateCurrentTeam({
                                                        conversations_settings: {
                                                            ...currentTeam?.conversations_settings,
                                                            widget_collect_name: checked,
                                                        },
                                                    })
                                                }}
                                            />
                                        </div>
                                        <LemonDivider />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Form title</label>
                                            <div className="flex gap-2 flex-1">
                                                <LemonInput
                                                    value={
                                                        identificationFormTitleValue ??
                                                        currentTeam?.conversations_settings
                                                            ?.widget_identification_form_title ??
                                                        'Before we start...'
                                                    }
                                                    placeholder="Enter form title"
                                                    onChange={setIdentificationFormTitleValue}
                                                    fullWidth
                                                />
                                                <LemonButton
                                                    type="primary"
                                                    onClick={saveIdentificationFormTitle}
                                                    disabledReason={
                                                        !identificationFormTitleValue ? 'Enter form title' : undefined
                                                    }
                                                >
                                                    Save
                                                </LemonButton>
                                            </div>
                                        </div>
                                        <LemonDivider />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Form description</label>
                                            <div className="flex gap-2 flex-1">
                                                <LemonInput
                                                    value={
                                                        identificationFormDescriptionValue ??
                                                        currentTeam?.conversations_settings
                                                            ?.widget_identification_form_description ??
                                                        'Please provide your details so we can help you better.'
                                                    }
                                                    placeholder="Enter form description"
                                                    onChange={setIdentificationFormDescriptionValue}
                                                    fullWidth
                                                />
                                                <LemonButton
                                                    type="primary"
                                                    onClick={saveIdentificationFormDescription}
                                                    disabledReason={
                                                        !identificationFormDescriptionValue
                                                            ? 'Enter form description'
                                                            : undefined
                                                    }
                                                >
                                                    Save
                                                </LemonButton>
                                            </div>
                                        </div>
                                    </>
                                )}
                            </LemonCard>
                        </SceneSection>
                        <div className="pt-8">
                            <div className="flex items-center gap-4 py-2 justify-between">
                                <div>
                                    <label className="w-40 shrink-0 font-medium">Public token</label>
                                    <p className="text-xs text-muted-alt mb-2">
                                        Automatically generated token used to authenticate widget requests.
                                    </p>
                                </div>
                                <div className="flex gap-2 flex-1">
                                    <LemonInput
                                        value={
                                            currentTeam?.conversations_settings?.widget_public_token ||
                                            'Token will be auto-generated on save'
                                        }
                                        disabledReason="Read-only after generation"
                                        fullWidth
                                    />
                                    {currentTeam?.conversations_settings?.widget_public_token && (
                                        <LemonButton type="secondary" status="danger" onClick={generateNewToken}>
                                            Regenerate
                                        </LemonButton>
                                    )}
                                </div>
                            </div>
                            <LemonBanner type="warning" className="my-2">
                                Only regenerate if you suspect it has been exposed or compromised.
                            </LemonBanner>
                        </div>
                    </>
                )}
            </LemonCard>
        </SceneSection>
    )
}
