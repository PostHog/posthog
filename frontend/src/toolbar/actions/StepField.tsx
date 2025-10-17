import clsx from 'clsx'
import { Field } from 'kea-forms'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { cssEscape } from 'lib/utils/cssEscape'

import { SelectorCount } from '~/toolbar/actions/SelectorCount'
import { ActionStepForm } from '~/toolbar/types'

import { URL_MATCHING_HINTS } from 'products/actions/frontend/utils/hints'

interface StepFieldProps {
    item: 'href' | 'text' | 'selector' | 'url'
    step: ActionStepForm
    label: string | JSX.Element
    caption?: string | JSX.Element
}

function hrefSelector(step: ActionStepForm): string | null {
    if (!step.href) {
        return null
    }
    // see https://developer.mozilla.org/en-US/docs/Web/CSS/Attribute_selectors#links
    const matchOperator = {
        // Link whose value is exactly step.href.
        ['exact']: '=',
        // Links with step.href anywhere in the URL
        ['contains']: '*=',
        // CSS selector can't match on regex
        ['regex']: null,
    }[step.href_matching || 'exact']

    if (!matchOperator) {
        return null
    }

    return `a[href${matchOperator}"${cssEscape(step.href)}"]`
}

export function StepField({ step, item, label, caption }: StepFieldProps): JSX.Element {
    const selected = step && step[`${item}_selected`]

    return (
        <>
            <div className={clsx('action-field my-1', selected && 'action-field-selected')}>
                <div>
                    {item === 'href' && step?.href && <SelectorCount selector={hrefSelector(step)} />}
                    {item === 'selector' && step?.selector && <SelectorCount selector={step.selector} />}
                    <Field name={`${item}_selected`} noStyle>
                        {({ onChange, value }) => <LemonCheckbox label={label} onChange={onChange} checked={value} />}
                    </Field>
                    {caption && <div className="action-field-caption">{caption}</div>}
                </div>
                {['url', 'href', 'text'].includes(item) ? (
                    <Field name={`${item}_matching`}>
                        {({ value, onChange }) => {
                            // match defaults in the data management section
                            if (value === undefined || value === null) {
                                item === 'url' ? (value = 'contains') : (value = 'exact')
                            }

                            return (
                                <LemonSegmentedButton
                                    fullWidth
                                    className={clsx('mb-1', !selected && 'opacity-50')}
                                    size="small"
                                    options={[
                                        { value: 'exact', label: 'Exact' },
                                        { value: 'regex', label: 'Regex' },
                                        { value: 'contains', label: 'Contains' },
                                    ]}
                                    value={value}
                                    onChange={onChange}
                                />
                            )
                        }}
                    </Field>
                ) : null}
                <Field name={item}>
                    {({ value, onChange }) => {
                        return item === 'selector' ? (
                            <LemonTextArea
                                className={clsx(!selected && 'opacity-50')}
                                onChange={onChange}
                                value={value ?? ''}
                                stopPropagation={true}
                            />
                        ) : (
                            <LemonInput
                                className={clsx(!selected && 'opacity-50')}
                                onChange={onChange}
                                value={value ?? ''}
                                stopPropagation={true}
                            />
                        )
                    }}
                </Field>
                {item === 'url' && step?.url_matching && step.url_matching in URL_MATCHING_HINTS ? (
                    <div className="action-field-hint">{URL_MATCHING_HINTS[step.url_matching]}</div>
                ) : null}
            </div>
        </>
    )
}
