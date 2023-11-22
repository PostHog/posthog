import { DefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopover'
import { genericOperatorToHumanName, propertyValueToHumanName } from 'lib/components/DefinitionPopover/utils'

import { ActionType } from '~/types'

import { PropertyKeyInfo } from '../PropertyKeyInfo'

export function ActionPopoverInfo({ entity }: { entity: ActionType }): JSX.Element | null {
    if (!entity) {
        return null
    }
    return (
        <>
            {entity.steps &&
                entity.steps.map((step, index) => (
                    <DefinitionPopover.Section key={step.id}>
                        <DefinitionPopover.Card
                            title={
                                <>
                                    Match group {index + 1}: <PropertyKeyInfo value={step.event} />
                                </>
                            }
                            value={
                                step.selector || step.text || step.href || step.url || step.properties?.length ? (
                                    <ul>
                                        {step.selector && (
                                            <li>
                                                <span>
                                                    Element matches CSS selector <b>{step.selector}</b>
                                                </span>
                                            </li>
                                        )}
                                        {step.text && (
                                            <li>
                                                <span>
                                                    Text equals{' '}
                                                    {step.text_matching === 'regex'
                                                        ? 'matches regex'
                                                        : step.url_matching === 'exact'
                                                        ? 'equals'
                                                        : 'contains'}{' '}
                                                    <b>{step.text}</b>
                                                </span>
                                            </li>
                                        )}
                                        {step.href && (
                                            <li>
                                                <span>
                                                    Href attribute{' '}
                                                    {step.href_matching === 'regex'
                                                        ? 'matches regex'
                                                        : step.url_matching === 'exact'
                                                        ? 'equals'
                                                        : 'contains'}
                                                    <b>{step.href}</b>
                                                </span>
                                            </li>
                                        )}
                                        {step.url && (
                                            <li>
                                                <span>
                                                    URL{' '}
                                                    {step.url_matching === 'regex'
                                                        ? 'matches regex'
                                                        : step.url_matching === 'exact'
                                                        ? 'equals'
                                                        : 'contains'}{' '}
                                                    <b>{step.url}</b>
                                                </span>
                                            </li>
                                        )}
                                        {step.properties &&
                                            step.properties.map((property, propIndex) => (
                                                <li key={propIndex}>
                                                    <span>
                                                        <PropertyKeyInfo value={property.key} />{' '}
                                                        {genericOperatorToHumanName(property)}{' '}
                                                        <b>{propertyValueToHumanName(property.value)}</b>
                                                    </span>
                                                </li>
                                            ))}
                                    </ul>
                                ) : null
                            }
                        />
                        {entity.steps && index < entity.steps.length - 1 && (
                            <DefinitionPopover.HorizontalLine style={{ marginTop: 4, marginBottom: 12 }}>
                                OR
                            </DefinitionPopover.HorizontalLine>
                        )}
                    </DefinitionPopover.Section>
                ))}
        </>
    )
}
