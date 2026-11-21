import { IconInfo, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    Field,
    FieldError,
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
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { VerticalNestedDND } from 'lib/components/VerticalNestedDND/VerticalNestedDND'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { CustomBotCondition, CustomBotField, CustomBotRule } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import {
    CUSTOM_BOT_CATEGORY,
    CUSTOM_BOT_CATEGORY_OPTIONS,
    CUSTOM_BOT_FIELD_OPTIONS,
    categoryLabel,
    combinerOptions,
    fieldLabel,
    matcherLabel,
    matcherOptionsFor,
    newCustomBotCondition,
    newCustomBotRule,
    patternPlaceholderFor,
    validateCustomBotCondition,
    validateCustomBotRule,
    withConditionKey,
} from './customBotRulesUtils'

function OptionSelect<T extends string>({
    value,
    options,
    onChange,
    disabledReason,
    ariaLabel,
}: {
    value: T
    options: { value: T; label: string; tooltip?: string }[]
    onChange: (value: T) => void
    disabledReason: string | null
    ariaLabel: string
}): JSX.Element {
    return (
        <Select<T> value={value} onValueChange={(next) => next !== null && onChange(next)}>
            <SelectTrigger aria-label={ariaLabel} disabledReason={disabledReason}>
                <SelectValue>{(selected: T) => options.find((option) => option.value === selected)?.label}</SelectValue>
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.tooltip ? (
                            <span className="flex flex-col">
                                <span>{option.label}</span>
                                <Text size="xs" variant="muted" render={<span />}>
                                    {option.tooltip}
                                </Text>
                            </span>
                        ) : (
                            option.label
                        )}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

function QuillReadOnlyBotRules({ rules }: { rules: CustomBotRule[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {rules.map((rule) => (
                <Item key={rule.id} variant="outline" size="sm">
                    <ItemContent>
                        <div className="flex flex-wrap items-center gap-2">
                            <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                                {rule.name}
                            </Text>
                            <Badge>{categoryLabel(rule.category)}</Badge>
                        </div>
                        {rule.items.length > 1 ? (
                            <ItemDescription>
                                When {rule.combiner === FilterLogicalOperator.Or ? 'any' : 'all'} of these conditions
                                are met:
                            </ItemDescription>
                        ) : null}
                        {rule.items.map((condition) => (
                            <Text key={condition.id} size="xs" render={<span className="m-0" />}>
                                {fieldLabel(condition.key)} {matcherLabel(condition.matcher)}{' '}
                                <code>{condition.pattern}</code>
                            </Text>
                        ))}
                    </ItemContent>
                </Item>
            ))}
        </div>
    )
}

export function QuillCustomBotRules({
    rules,
    onRulesChange,
    testValues,
    onTestValuesChange,
    restrictedReason,
    droppedCount,
    usedFields,
    matched,
    hasTestInput,
    ipRulesAreDead,
    hasSavedRules,
    saving,
    onSave,
    addConditionDisabledReason,
    addBotDisabledReason,
    saveDisabledReason,
}: {
    rules: CustomBotRule[]
    onRulesChange: (rules: CustomBotRule[]) => void
    testValues: Partial<Record<CustomBotField, string>>
    onTestValuesChange: (testValues: Partial<Record<CustomBotField, string>>) => void
    restrictedReason: string | null
    droppedCount: number
    usedFields: { value: CustomBotField; label: string }[]
    matched: CustomBotRule[]
    hasTestInput: boolean
    ipRulesAreDead: boolean
    hasSavedRules: boolean
    saving: boolean
    onSave: () => void
    addConditionDisabledReason: (rule: CustomBotRule) => string | undefined
    addBotDisabledReason: string | undefined
    saveDisabledReason: string | undefined
}): JSX.Element {
    const canEdit = !restrictedReason

    return (
        <div className="flex flex-col gap-4">
            <Text size="xs" render={<p className="m-0" />}>
                A bot you add here counts as a bot everywhere <code>Is bot</code> is available, including insights, web
                analytics, and SQL. PostHog's built-in list already covers crawlers that identify themselves, like
                GPTBot and Googlebot. Your rules are checked first, so you can give one of those a different name or
                category.
            </Text>
            <Text size="xs" render={<p className="m-0" />}>
                Match the user agent to catch a crawler that names itself, the IP address to catch one that sends a
                browser user agent from a range you know, or combine conditions to catch one that only stands out
                through a combination, like an 800x600 screen.{' '}
                <Button
                    variant="link"
                    size="inline"
                    nativeButton={false}
                    render={<LinkPrimitive to="https://posthog.com/docs/web-analytics/bot-detection" target="_blank" />}
                >
                    Read more about bot detection
                </Button>
            </Text>

            {rules.length === 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    No bots added yet. PostHog's built-in list still applies. Add one to extend it.
                </Text>
            ) : null}

            {droppedCount > 0 ? (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            {droppedCount === 1 ? 'One saved rule' : `${droppedCount} saved rules`} could not be read
                            and will be removed if you save. Contact support if you did not expect this.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            ) : null}

            {!canEdit ? (
                <QuillReadOnlyBotRules rules={rules} />
            ) : (
                <VerticalNestedDND<CustomBotCondition, CustomBotRule>
                    initialItems={rules}
                    onChange={onRulesChange}
                    renderContainerItem={(rule, { updateContainerItem }) => {
                        const ruleError = validateCustomBotRule(rule)
                        return (
                            <div className="flex flex-col gap-2">
                                <div className="flex flex-wrap items-center gap-2">
                                    <Text size="xs" render={<span className="m-0" />}>
                                        Flag as bot
                                    </Text>
                                    <Input
                                        className="min-w-40 flex-1"
                                        aria-label="Bot name"
                                        value={rule.name}
                                        onChange={(event) => updateContainerItem({ ...rule, name: event.target.value })}
                                        placeholder="Acme scraper"
                                    />
                                    <Text size="xs" render={<span className="m-0" />}>
                                        in category
                                    </Text>
                                    <OptionSelect
                                        value={rule.category || CUSTOM_BOT_CATEGORY}
                                        options={CUSTOM_BOT_CATEGORY_OPTIONS}
                                        onChange={(category) => updateContainerItem({ ...rule, category })}
                                        disabledReason={restrictedReason}
                                        ariaLabel="Category"
                                    />
                                </div>
                                {rule.items.length === 1 ? (
                                    <Text size="xs" render={<span className="m-0" />}>
                                        when this condition is met
                                    </Text>
                                ) : (
                                    <div className="flex flex-wrap items-center gap-2">
                                        <Text size="xs" render={<span className="m-0" />}>
                                            when
                                        </Text>
                                        <OptionSelect
                                            value={rule.combiner}
                                            options={combinerOptions}
                                            onChange={(combiner) => updateContainerItem({ ...rule, combiner })}
                                            disabledReason={restrictedReason}
                                            ariaLabel="Condition match"
                                        />
                                        <Text size="xs" render={<span className="m-0" />}>
                                            conditions are met
                                        </Text>
                                    </div>
                                )}
                                {ruleError && !rule.items.some(validateCustomBotCondition) ? (
                                    <Text size="xs" variant="destructive" render={<span className="m-0" />}>
                                        {ruleError}
                                    </Text>
                                ) : null}
                            </div>
                        )
                    }}
                    renderChildItem={(condition, { updateChildItem }) => {
                        const error = validateCustomBotCondition(condition)
                        return (
                            <Field className="w-full" data-invalid={error ? true : undefined}>
                                <div className="flex flex-wrap items-center gap-2">
                                    <OptionSelect
                                        value={condition.key}
                                        options={CUSTOM_BOT_FIELD_OPTIONS}
                                        onChange={(key) => updateChildItem(withConditionKey(condition, key))}
                                        disabledReason={restrictedReason}
                                        ariaLabel="Property"
                                    />
                                    <OptionSelect
                                        value={condition.matcher}
                                        options={matcherOptionsFor(condition.key)}
                                        onChange={(matcher) => updateChildItem({ ...condition, matcher })}
                                        disabledReason={restrictedReason}
                                        ariaLabel="Operator"
                                    />
                                    <Input
                                        className="min-w-40 flex-1 font-mono"
                                        aria-label="Pattern"
                                        aria-invalid={error ? true : undefined}
                                        value={condition.pattern}
                                        onChange={(event) =>
                                            updateChildItem({ ...condition, pattern: event.target.value })
                                        }
                                        placeholder={patternPlaceholderFor(condition.key, condition.matcher)}
                                    />
                                </div>
                                {error ? <FieldError>{error}</FieldError> : null}
                            </Field>
                        )
                    }}
                    renderAddChildItem={(rule, { onAddChild }) => (
                        <Button
                            variant="outline"
                            onClick={() => onAddChild(rule.id)}
                            data-attr="custom-bot-rules-add-condition"
                            disabledReason={addConditionDisabledReason(rule)}
                        >
                            <IconPlus />
                            Add condition
                        </Button>
                    )}
                    renderAddContainerItem={({ onAddContainer }) => (
                        <Button
                            variant="outline"
                            onClick={onAddContainer}
                            data-attr="custom-bot-rules-add-rule"
                            disabledReason={addBotDisabledReason}
                        >
                            <IconPlus />
                            Add bot
                        </Button>
                    )}
                    renderAdditionalControls={() => (
                        <Button
                            variant="primary"
                            onClick={onSave}
                            loading={saving}
                            data-attr="custom-bot-rules-save"
                            disabledReason={saveDisabledReason}
                        >
                            Save
                        </Button>
                    )}
                    createNewContainerItem={newCustomBotRule}
                    createNewChildItem={newCustomBotCondition}
                />
            )}

            {ipRulesAreDead ? (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            This project anonymizes IP addresses, so events arrive without one and a condition on the IP
                            address never matches. Turn off "Discard client IP data" in your project settings, or match
                            on another property.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            ) : null}

            {usedFields.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <FieldLabel className="flex items-center gap-1">
                        Test a value
                        <Tooltip>
                            <TooltipTrigger
                                delay={0}
                                render={<Button size="icon-xs" aria-label="About testing a value" />}
                            >
                                <IconInfo />
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">
                                Only your own bots are checked here. A real query also matches PostHog's built-in list,
                                after your rules.
                            </TooltipContent>
                        </Tooltip>
                    </FieldLabel>
                    {usedFields.map((field) => (
                        <Field key={field.value} orientation="horizontal" className="flex-wrap items-center">
                            <FieldLabel htmlFor={`custom-bot-test-${field.value}`} className="w-32 shrink-0">
                                {field.label}
                            </FieldLabel>
                            <Input
                                id={`custom-bot-test-${field.value}`}
                                className="min-w-40 flex-1 font-mono"
                                value={testValues[field.value] ?? ''}
                                onChange={(event) =>
                                    onTestValuesChange({ ...testValues, [field.value]: event.target.value })
                                }
                                placeholder={
                                    field.value === CustomBotField.IP ? '192.0.2.55' : `Paste a ${field.label}`
                                }
                            />
                        </Field>
                    ))}
                    {matched.length > 0 ? (
                        <span className="flex flex-wrap items-center gap-1">
                            <Text size="xs" render={<span className="m-0" />}>
                                Matches
                            </Text>
                            {matched.map((rule) => (
                                <Badge key={rule.id} variant="success">
                                    {rule.name || fieldLabel(rule.items[0]?.key ?? CustomBotField.RawUserAgent)}
                                </Badge>
                            ))}
                        </span>
                    ) : hasTestInput ? (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            No custom rule matched. PostHog's built-in list still applies.
                        </Text>
                    ) : null}
                </div>
            ) : null}

            {hasSavedRules ? (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Changes apply to new and existing data. Refresh an insight or dashboard to see them applied.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            ) : null}
        </div>
    )
}
