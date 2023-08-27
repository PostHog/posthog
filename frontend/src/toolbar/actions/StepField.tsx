import { SelectorCount } from '~/toolbar/actions/SelectorCount'
import { cssEscape } from 'lib/utils/cssEscape'
import { ActionStepForm } from '~/toolbar/types'
import { URL_MATCHING_HINTS } from 'scenes/actions/hints'
import { Field } from 'kea-forms'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { StringMatching } from '~/types'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

interface StepFieldProps {
    item: 'href' | 'text' | 'selector' | 'url'
    step: ActionStepForm
    label: string | JSX.Element
    caption?: string | JSX.Element
}

export function StepField({ step, item, label, caption }: StepFieldProps): JSX.Element {
    const selected = step && ((step as any)[`${item}_selected`] as boolean)
    // const fieldStyle = selected ? {} : { opacity: 0.5 }

    return (
        <>
            <div className={selected ? 'action-field action-field-selected' : 'action-field'}>
                <div>
                    {item === 'href' && step?.href && <SelectorCount selector={`a[href="${cssEscape(step.href)}"]`} />}
                    {item === 'selector' && step?.selector && <SelectorCount selector={step.selector} />}
                    <Field name={`${item}_selected`} noStyle>
                        {({ onChange, value }) => <LemonCheckbox label={label} onChange={onChange} checked={value} />}
                    </Field>
                    {caption && <div className="action-field-caption">{caption}</div>}
                </div>
                {['url', 'href', 'text'].includes(item) ? (
                    <Field name={`${item}_matching`}>
                        <LemonSegmentedButton
                            size={'small'}
                            options={[
                                { value: StringMatching.Exact, label: 'Exact match' },
                                { value: StringMatching.Regex, label: 'Regex' },
                                { value: StringMatching.Contains, label: 'Contains' },
                            ]}
                        />
                    </Field>
                ) : null}
                <Field name={item}>{item === 'selector' ? <LemonTextArea /> : <LemonInput />}</Field>
                {item === 'url' && step?.url_matching && step.url_matching in URL_MATCHING_HINTS ? (
                    <div className="action-field-hint">{URL_MATCHING_HINTS[step.url_matching]}</div>
                ) : null}
            </div>
        </>
    )
}
