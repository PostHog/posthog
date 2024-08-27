import clsx from 'clsx'
import { Field } from 'kea-forms'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { URL_MATCHING_HINTS } from 'scenes/actions/hints'

import { SelectorCount } from '~/toolbar/actions/SelectorCount'
import {WebExperimentTransform} from '~/toolbar/types'
import {LemonField} from "lib/lemon-ui/LemonField";

interface WebExperimentTransformFieldProps {
    transform: WebExperimentTransform
}

export function WebExperimentTransformField({ transform }: WebExperimentTransformFieldProps): JSX.Element {
    console.log(`transform is `, transform)
    return (
        <>
            <div className={clsx('action-field my-1', 'action-field-selected')}>
                <LemonField.Pure label='text content'>
                        <LemonTextArea
                        onChange={(val) =>
                            transform.text = val
                        }
                            value={transform.text} />
                </LemonField.Pure>
                <LemonField label='html content' name='html'>
                        {({ value }) => <LemonTextArea  value={value} />}
                </LemonField>
                <LemonField label='css Classname' name='className'>
                        {({ value }) => <LemonTextArea  value={value} />}
                </LemonField>
                <LemonField label='image URL' name='imgUrl'>
                        {({ value }) => <LemonTextArea  value={value} />}
                </LemonField>
            </div>
        </>
    )
}
