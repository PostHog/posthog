import {IconAIText, IconCode, IconMessage} from "@posthog/icons";
import { Field } from 'kea-forms'
import {LemonSegmentedButton, LemonSegmentedButtonOption} from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import {useState} from "react";

import {WebExperimentTransform} from '~/toolbar/types'
import {useActions, useValues} from "kea";
import {experimentsTabLogic} from "~/toolbar/experiments/experimentsTabLogic";

interface WebExperimentTransformFieldProps {
    variant: string
    tIndex: number
    transform: WebExperimentTransform
}
type elementTransformKind = 'html' | 'text' | 'css'
const ELEMENT_TRANSFORM_OPTIONS: LemonSegmentedButtonOption<elementTransformKind>[] = [
    {
        value: 'html',
        label: 'HTML',
        icon: <IconCode />,
    },
    {
        value: 'text',
        label: 'Text',
        icon: <IconMessage />,
    },
    {
        value: 'css',
        label: 'CSS',
        icon: <IconAIText />,
    },
]

export function WebExperimentTransformField({ variant, tIndex, transform }: WebExperimentTransformFieldProps): JSX.Element {
    const [transformSelected, setTransformSelected] = useState(transform.html ? "html": transform.text ? "text" : "css")
    const {
        experimentForm,
    } = useValues(experimentsTabLogic)
    const {
        setExperimentFormValue,
    } = useActions(experimentsTabLogic)
    return (
        <>
            <LemonSegmentedButton fullWidth options={ELEMENT_TRANSFORM_OPTIONS}
                                  onChange={(e) => setTransformSelected(e)}
            value ={transformSelected}/>
            { transformSelected == 'text' && (
                <LemonTextArea
                    value={transform.text}
                    stopPropagation={true}
                />
            )}

            { transformSelected == 'html' && (
                <LemonTextArea
                    onChange={(value)=>{
                        console.log(`changing html to ${value}`)
                        transform.html = value
                        if(experimentForm.variants) {
                            const webVariant = experimentForm.variants[variant]
                            if (webVariant) {
                                webVariant.transforms[tIndex].html = value
                            }
                        }
                        setExperimentFormValue('variants', experimentForm.variants )
                    }}
                    value={transform.html}
                />
            )}

            { transformSelected == 'css' && (
                <LemonTextArea
                    onChange={(value)=>{
                        transform.className = value
                    }}
                    value={transform.className}
                    stopPropagation={true}
                />
            )}
        </>
    )
}
