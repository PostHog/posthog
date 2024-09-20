import './ConditionalFormattingTab.scss'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonSelect, LemonTag, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGBA, lightenDarkenColor, RGBToHex, RGBToRGBA } from 'lib/utils'
import { useState } from 'react'
import { ColorResult, TwitterPicker } from 'react-color'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ConditionalFormattingRule } from '~/queries/schema'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { FORMATTING_TEMPLATES } from '../../types'
import { conditionalFormattingLogic } from './conditionalFormattingLogic'

const getRuleHeader = (rule: ConditionalFormattingRule): string => {
    if (!rule.columnName || !rule.input) {
        return 'New rule'
    }

    const template = FORMATTING_TEMPLATES.find((n) => n.id === rule.templateId)

    if (!template) {
        return 'New rule'
    }

    if (template.hideInput) {
        return `${rule.columnName} ${template.label.toLowerCase()}`
    }

    return `${rule.columnName} ${template.label.toLowerCase()} ${rule.input}`
}

export const ConditionalFormattingTab = (): JSX.Element => {
    const { isDarkModeOn } = useValues(themeLogic)
    const { conditionalFormattingRules, conditionalFormattingRulesPanelActiveKeys } = useValues(dataVisualizationLogic)
    const { addConditionalFormattingRule, setConditionalFormattingRulesPanelActiveKeys } =
        useActions(dataVisualizationLogic)

    return (
        <div className="flex flex-col w-full ConditionalFormattingTab">
            <p>You can add rules to make the cells in the table change color if they meet certain conditions.</p>

            {conditionalFormattingRules.length > 0 && (
                <LemonCollapse
                    activeKeys={conditionalFormattingRulesPanelActiveKeys}
                    onChange={(activeKeys) => setConditionalFormattingRulesPanelActiveKeys(activeKeys)}
                    multiple={true}
                    className="mb-2"
                    size="small"
                    panels={conditionalFormattingRules.map((rule) => ({
                        key: rule.id,
                        header: (
                            <>
                                <SeriesGlyph
                                    style={{
                                        borderColor: rule.color,
                                        color: rule.color,
                                        backgroundColor: isDarkModeOn
                                            ? RGBToRGBA(lightenDarkenColor(rule.color, -20), 0.3)
                                            : hexToRGBA(rule.color, 0.2),
                                    }}
                                >
                                    <></>
                                </SeriesGlyph>
                                <span className="ml-2">{getRuleHeader(rule)}</span>
                            </>
                        ),
                        content: <RuleItem rule={rule} key={rule.id} />,
                    }))}
                />
            )}

            <LemonButton
                className="mt-1"
                onClick={() => addConditionalFormattingRule()}
                icon={<IconPlusSmall />}
                fullWidth
                type="secondary"
            >
                Add rule
            </LemonButton>
        </div>
    )
}

const DEFAULT_PICKER_COLORS = [
    '#FFADAD', // Current default
    '#E8A598',
    '#FFD6A5',
    '#FFCFD2',
    '#FDFFB6',
    '#C1FBA4',
    '#9BF6FF',
    '#A0C4FF',
    '#BDB2FF',
    '#FFC6FF',
]

const ColourPickerButton = ({
    color,
    onColorSelect: propOnColorSelect,
}: {
    color: string
    onColorSelect?: (color: string) => void
}): JSX.Element => {
    const [pickerOpen, setPickerOpen] = useState(false)
    const { isDarkModeOn } = useValues(themeLogic)

    const onColorSelect = (colorResult: ColorResult): void => {
        if (propOnColorSelect) {
            propOnColorSelect(colorResult.hex)
        }

        if (DEFAULT_PICKER_COLORS.includes(colorResult.hex)) {
            setPickerOpen(false)
        }
    }

    const colors = isDarkModeOn
        ? DEFAULT_PICKER_COLORS.map((n) => RGBToHex(lightenDarkenColor(n, -30)))
        : DEFAULT_PICKER_COLORS

    return (
        <Popover
            visible={pickerOpen}
            overlay={<TwitterPicker color={color} colors={colors} onChangeComplete={onColorSelect} />}
            onClickOutside={() => setPickerOpen(false)}
            padded={false}
        >
            <LemonButton
                type="secondary"
                onClick={() => setPickerOpen(!pickerOpen)}
                sideIcon={<></>}
                className="ConditionalFormattingTab__ColorPicker"
            >
                <SeriesGlyph
                    style={{
                        borderColor: color,
                        color: color,
                        backgroundColor: isDarkModeOn
                            ? RGBToRGBA(lightenDarkenColor(color, -20), 0.3)
                            : hexToRGBA(color, 0.5),
                    }}
                >
                    <></>
                </SeriesGlyph>
            </LemonButton>
        </Popover>
    )
}

const RuleItem = ({ rule: propsRule }: { rule: ConditionalFormattingRule }): JSX.Element => {
    const { columns, responseLoading, dataVisualizationProps } = useValues(dataVisualizationLogic)

    const builtCFLogic = conditionalFormattingLogic({ key: dataVisualizationProps.key, rule: propsRule })

    const { selectColumn, updateInput, selectTemplate, selectColor, deleteRule } = useActions(builtCFLogic)
    const { rule, template } = useValues(builtCFLogic)

    return (
        <div className="gap-2 flex flex-col">
            <LemonSelect
                placeholder="Column"
                className="w-full"
                value={rule.columnName || null}
                options={columns.map(({ name, type }) => ({
                    value: name,
                    label: (
                        <div className="items-center flex-1">
                            {name}
                            <LemonTag className="ml-2" type="default">
                                {type.name}
                            </LemonTag>
                        </div>
                    ),
                }))}
                disabledReason={responseLoading ? 'Query loading...' : undefined}
                onChange={(value) => {
                    const column = columns.find((n) => n.name === value)
                    if (column) {
                        selectColumn(column.name)
                    }
                }}
            />

            <LemonSelect
                className="w-full"
                options={FORMATTING_TEMPLATES.filter((n) => {
                    const column = columns.find((n) => n.name === rule.columnName)
                    return column ? n.availableColumnTypes.includes(column.type.name) : true
                }).map(({ id, label }) => ({ label, value: id }))}
                value={rule.templateId}
                onSelect={(value) => selectTemplate(value)}
            />

            <div className="flex flex-1">
                <ColourPickerButton color={rule.color} onColorSelect={selectColor} />
                <LemonInput
                    placeholder="value"
                    className="ml-2 flex-1"
                    onChange={(value) => updateInput(value)}
                    value={rule.input}
                    disabled={template.hideInput}
                />
                <LemonButton
                    icon={<IconTrash />}
                    status="danger"
                    title="Delete rule"
                    className="ml-1"
                    noPadding
                    tooltip="Delete formatting rule"
                    onClick={() => deleteRule()}
                />
            </div>
        </div>
    )
}
