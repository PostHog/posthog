import { useActions, useValues } from 'kea'

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

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ConversationsSettings } from '~/types'

import { QuillWidgetSection } from '../../components/QuillWidgetSection/QuillWidgetSection'
import { WebAndApiAccessSummary } from '../../components/WebAndApiAccessSummary/WebAndApiAccessSummary'
import { supportSettingsLogic } from './supportSettingsLogic'
import { WIDGET_COLORS, WIDGET_POSITION_OPTIONS } from './widgetSettingsOptions'

export function WidgetSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const {
        generateNewToken,
        setWidgetEnabledLoading,
        setGreetingInputValue,
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
        greetingInputValue,
        identificationFormTitleValue,
        identificationFormDescriptionValue,
        placeholderTextValue,
    } = useValues(supportSettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const greetingText =
        greetingInputValue ??
        currentTeam?.conversations_settings?.widget_greeting_text ??
        'Hey, how can I help you today?'
    const placeholderText =
        placeholderTextValue ?? currentTeam?.conversations_settings?.widget_placeholder_text ?? 'Type your message...'
    const identificationFormTitle =
        identificationFormTitleValue ??
        currentTeam?.conversations_settings?.widget_identification_form_title ??
        'Before we start...'
    const identificationFormDescription =
        identificationFormDescriptionValue ??
        currentTeam?.conversations_settings?.widget_identification_form_description ??
        'Please provide your details so we can help you better.'

    function handleWidgetEnabledChange(checked: boolean): void {
        setWidgetEnabledLoading(true)
        updateCurrentTeam({
            conversations_settings: {
                ...currentTeam?.conversations_settings,
                widget_enabled: checked,
            },
        })
    }

    function handleWidgetColorChange(color: string): void {
        updateCurrentTeam({
            conversations_settings: {
                ...currentTeam?.conversations_settings,
                widget_color: color,
            },
        })
    }

    function handleWidgetPositionChange(value: NonNullable<ConversationsSettings['widget_position']>): void {
        updateCurrentTeam({
            conversations_settings: {
                ...currentTeam?.conversations_settings,
                widget_position: value,
            },
        })
    }

    function handleRequireEmailChange(checked: boolean): void {
        updateCurrentTeam({
            conversations_settings: {
                ...currentTeam?.conversations_settings,
                widget_require_email: checked,
            },
        })
    }

    function handleCollectNameChange(checked: boolean): void {
        updateCurrentTeam({
            conversations_settings: {
                ...currentTeam?.conversations_settings,
                widget_collect_name: checked,
            },
        })
    }

    if (todayRailNav) {
        return (
            <QuillWidgetSection
                settings={currentTeam?.conversations_settings}
                widgetEnabledLoading={widgetEnabledLoading}
                greetingText={greetingText}
                placeholderText={placeholderText}
                identificationFormTitle={identificationFormTitle}
                identificationFormDescription={identificationFormDescription}
                greetingInputValue={greetingInputValue}
                placeholderTextValue={placeholderTextValue}
                identificationFormTitleValue={identificationFormTitleValue}
                identificationFormDescriptionValue={identificationFormDescriptionValue}
                onWidgetEnabledChange={handleWidgetEnabledChange}
                onWidgetColorChange={handleWidgetColorChange}
                onWidgetPositionChange={handleWidgetPositionChange}
                onRequireEmailChange={handleRequireEmailChange}
                onCollectNameChange={handleCollectNameChange}
                onGreetingInputChange={setGreetingInputValue}
                onSaveGreeting={saveGreetingText}
                onPlaceholderTextChange={setPlaceholderTextValue}
                onSavePlaceholderText={savePlaceholderText}
                onIdentificationFormTitleChange={setIdentificationFormTitleValue}
                onSaveIdentificationFormTitle={saveIdentificationFormTitle}
                onIdentificationFormDescriptionChange={setIdentificationFormDescriptionValue}
                onSaveIdentificationFormDescription={saveIdentificationFormDescription}
                onRegenerateToken={generateNewToken}
            />
        )
    }

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
                        onChange={handleWidgetEnabledChange}
                        loading={widgetEnabledLoading}
                    />
                </div>

                {currentTeam?.conversations_settings?.widget_enabled && (
                    <>
                        <LemonDivider />
                        <WebAndApiAccessSummary />
                        <SceneSection title="Visual settings" className="mt-8" titleSize="sm">
                            <LemonCard hoverEffect={false} className="px-4 py-3">
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Button color</label>
                                    <LemonColorPicker
                                        colors={WIDGET_COLORS}
                                        selectedColor={currentTeam?.conversations_settings?.widget_color || '#1d4aff'}
                                        onSelectColor={handleWidgetColorChange}
                                        showCustomColor
                                    />
                                </div>
                                <LemonDivider />
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Widget position</label>
                                    <LemonSelect
                                        value={currentTeam?.conversations_settings?.widget_position || 'bottom_right'}
                                        onChange={handleWidgetPositionChange}
                                        options={WIDGET_POSITION_OPTIONS}
                                    />
                                </div>
                                <LemonDivider />
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Greeting message</label>
                                    <div className="flex gap-2 flex-1">
                                        <LemonInput
                                            value={greetingText}
                                            placeholder="Enter greeting message"
                                            onChange={setGreetingInputValue}
                                            fullWidth
                                        />
                                        <LemonButton
                                            type="primary"
                                            onClick={saveGreetingText}
                                            disabledReason={
                                                !greetingInputValue ? 'Enter a greeting message' : undefined
                                            }
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
                                            value={placeholderText}
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
                                        onChange={handleRequireEmailChange}
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
                                                onChange={handleCollectNameChange}
                                            />
                                        </div>
                                        <LemonDivider />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Form title</label>
                                            <div className="flex gap-2 flex-1">
                                                <LemonInput
                                                    value={identificationFormTitle}
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
                                                    value={identificationFormDescription}
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
