import { useId } from 'react'

import {
    Button,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    Input,
    Item,
    ItemContent,
    ItemDescription,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
} from '@posthog/quill'

import { LemonColorPicker } from 'lib/lemon-ui/LemonColor/LemonColorPicker'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ConversationsSettings } from '~/types'

import { WIDGET_COLORS, WIDGET_POSITION_OPTIONS } from '../../scenes/settings/widgetSettingsOptions'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { QuillSettingsSwitchRow } from '../QuillSettingsSwitchRow/QuillSettingsSwitchRow'
import { QuillWidgetTextField } from '../QuillWidgetTextField/QuillWidgetTextField'
import { WebAndApiAccessSummary } from '../WebAndApiAccessSummary/WebAndApiAccessSummary'

type WidgetPosition = NonNullable<ConversationsSettings['widget_position']>

export function QuillWidgetSection({
    settings,
    widgetEnabledLoading,
    greetingText,
    placeholderText,
    identificationFormTitle,
    identificationFormDescription,
    greetingInputValue,
    placeholderTextValue,
    identificationFormTitleValue,
    identificationFormDescriptionValue,
    onWidgetEnabledChange,
    onWidgetColorChange,
    onWidgetPositionChange,
    onRequireEmailChange,
    onCollectNameChange,
    onGreetingInputChange,
    onSaveGreeting,
    onPlaceholderTextChange,
    onSavePlaceholderText,
    onIdentificationFormTitleChange,
    onSaveIdentificationFormTitle,
    onIdentificationFormDescriptionChange,
    onSaveIdentificationFormDescription,
    onRegenerateToken,
}: {
    settings: ConversationsSettings | null | undefined
    widgetEnabledLoading: boolean
    greetingText: string
    placeholderText: string
    identificationFormTitle: string
    identificationFormDescription: string
    greetingInputValue: string | null
    placeholderTextValue: string | null
    identificationFormTitleValue: string | null
    identificationFormDescriptionValue: string | null
    onWidgetEnabledChange: (checked: boolean) => void
    onWidgetColorChange: (color: string) => void
    onWidgetPositionChange: (position: WidgetPosition) => void
    onRequireEmailChange: (checked: boolean) => void
    onCollectNameChange: (checked: boolean) => void
    onGreetingInputChange: (value: string) => void
    onSaveGreeting: () => void
    onPlaceholderTextChange: (value: string) => void
    onSavePlaceholderText: () => void
    onIdentificationFormTitleChange: (value: string) => void
    onSaveIdentificationFormTitle: () => void
    onIdentificationFormDescriptionChange: (value: string) => void
    onSaveIdentificationFormDescription: () => void
    onRegenerateToken: () => void
}): JSX.Element {
    const positionId = useId()
    const tokenId = useId()

    return (
        <QuillSettingsSubsection
            title="In-app widget"
            description={
                <>
                    Add a chat widget to your website for customers to reach you.{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/docs/support/widget" target="_blank" />}
                    >
                        Docs
                    </Button>
                    . For logged-in users, use{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://posthog.com/docs/support/javascript-api#user-identification"
                                target="_blank"
                            />
                        }
                    >
                        identity verification
                    </Button>{' '}
                    so tickets persist across browsers and devices.
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <QuillSettingsSwitchRow
                    label="Enable in-app widget"
                    description="Turn on the in-app support widget to start receiving messages from your users"
                    checked={!!settings?.widget_enabled}
                    onCheckedChange={onWidgetEnabledChange}
                    loading={widgetEnabledLoading}
                />

                {settings?.widget_enabled && (
                    <>
                        <Separator />
                        <WebAndApiAccessSummary />

                        <QuillSettingsSubsection title="Visual settings">
                            <div className="flex flex-col gap-3">
                                <Field orientation="horizontal" className="flex-wrap">
                                    <FieldLabel>Button color</FieldLabel>
                                    <LemonColorPicker
                                        colors={WIDGET_COLORS}
                                        selectedColor={settings?.widget_color || '#1d4aff'}
                                        onSelectColor={onWidgetColorChange}
                                        showCustomColor
                                    />
                                </Field>
                                <Field>
                                    <FieldLabel htmlFor={positionId}>Widget position</FieldLabel>
                                    <Select
                                        items={WIDGET_POSITION_OPTIONS}
                                        value={settings?.widget_position || 'bottom_right'}
                                        onValueChange={(value) =>
                                            value && onWidgetPositionChange(value as WidgetPosition)
                                        }
                                    >
                                        <SelectTrigger id={positionId} className="w-fit">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {WIDGET_POSITION_OPTIONS.map((option) => (
                                                <SelectItem key={option.value} value={option.value}>
                                                    {option.label}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </Field>
                                <QuillWidgetTextField
                                    label="Greeting message"
                                    value={greetingText}
                                    placeholder="Enter greeting message"
                                    saveDisabledReason={!greetingInputValue ? 'Enter a greeting message' : undefined}
                                    onChange={onGreetingInputChange}
                                    onSave={onSaveGreeting}
                                />
                                <QuillWidgetTextField
                                    label="Placeholder text"
                                    value={placeholderText}
                                    placeholder="Enter placeholder text"
                                    saveDisabledReason={!placeholderTextValue ? 'Enter placeholder text' : undefined}
                                    onChange={onPlaceholderTextChange}
                                    onSave={onSavePlaceholderText}
                                />
                            </div>
                        </QuillSettingsSubsection>

                        <QuillSettingsSubsection title="Identification form">
                            <div className="flex flex-col gap-3">
                                <QuillSettingsSwitchRow
                                    label="Require email"
                                    description="Require user to enter their email address to start the chat."
                                    checked={!!settings?.widget_require_email}
                                    onCheckedChange={onRequireEmailChange}
                                />

                                {settings?.widget_require_email && (
                                    <>
                                        <QuillSettingsSwitchRow
                                            label="Collect name"
                                            description="Collect user's name to personalize the chat."
                                            checked={!!settings?.widget_collect_name}
                                            onCheckedChange={onCollectNameChange}
                                        />
                                        <QuillWidgetTextField
                                            label="Form title"
                                            value={identificationFormTitle}
                                            placeholder="Enter form title"
                                            saveDisabledReason={
                                                !identificationFormTitleValue ? 'Enter form title' : undefined
                                            }
                                            onChange={onIdentificationFormTitleChange}
                                            onSave={onSaveIdentificationFormTitle}
                                        />
                                        <QuillWidgetTextField
                                            label="Form description"
                                            value={identificationFormDescription}
                                            placeholder="Enter form description"
                                            saveDisabledReason={
                                                !identificationFormDescriptionValue
                                                    ? 'Enter form description'
                                                    : undefined
                                            }
                                            onChange={onIdentificationFormDescriptionChange}
                                            onSave={onSaveIdentificationFormDescription}
                                        />
                                    </>
                                )}
                            </div>
                        </QuillSettingsSubsection>

                        <Separator />

                        <Field>
                            <FieldContent>
                                <FieldLabel htmlFor={tokenId}>Public token</FieldLabel>
                                <FieldDescription>
                                    Automatically generated token used to authenticate widget requests.
                                </FieldDescription>
                            </FieldContent>
                            <div className="flex flex-wrap gap-2">
                                <Input
                                    id={tokenId}
                                    className="min-w-60 flex-1"
                                    value={settings?.widget_public_token || 'Token will be auto-generated on save'}
                                    disabledReason="Read-only after generation"
                                    readOnly
                                />
                                {settings?.widget_public_token && (
                                    <Button variant="destructive-outline" onClick={onRegenerateToken}>
                                        Regenerate
                                    </Button>
                                )}
                            </div>
                        </Field>
                        <Item tone="warning" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    Only regenerate if you suspect it has been exposed or compromised.
                                </ItemDescription>
                            </ItemContent>
                        </Item>
                    </>
                )}
            </div>
        </QuillSettingsSubsection>
    )
}
