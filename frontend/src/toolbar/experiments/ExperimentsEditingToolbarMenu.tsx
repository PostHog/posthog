import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { useEffect, useMemo } from 'react'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { experimentsLogic } from '~/toolbar/experiments/experimentsLogic'
import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentVariant } from '~/toolbar/experiments/WebExperimentVariant'
import { WebExperimentVariantHeader } from '~/toolbar/experiments/WebExperimentVariantHeader'

export const ExperimentsEditingToolbarMenu = (): JSX.Element => {
    const { getExperiments } = useActions(experimentsLogic)
    const { selectedExperimentId, experimentForm, addVariantAvailable, selectedVariant, experimentFormErrors } =
        useValues(experimentsTabLogic)
    const {
        selectExperiment,
        selectVariant,
        inspectForElementWithIndex,
        addNewVariant,
        applyVariant,
        setExperimentFormValue,
    } = useActions(experimentsTabLogic)

    useMemo(() => {
        if (selectedExperimentId === 'new') {
            selectVariant('test')
            inspectForElementWithIndex('test', 'all-elements', 0)
        }
    }, [selectedExperimentId, selectVariant, inspectForElementWithIndex])

    useEffect(() => {
        getExperiments()
    }, [])

    return (
        <ToolbarMenu>
            <Form
                name="experiment"
                logic={experimentsTabLogic}
                formKey="experimentForm"
                enableFormOnSubmit
                className="flex flex-col overflow-hidden flex-1"
            >
                <ToolbarMenu.Header className="border-b">
                    <h1 className="p-1 font-bold text-sm mb-0">
                        {selectedExperimentId === 'new' ? 'New ' : 'Edit '}
                        experiment
                        {selectedVariant && `  variant : ${selectedVariant}`}
                    </h1>
                    <div id="errorcontainer">
                        {Object.keys(experimentFormErrors).length > 0 &&
                            !Object.values(experimentFormErrors).every((el) => el === undefined) && (
                                <LemonBanner type="error">
                                    <ol>
                                        {experimentFormErrors.name && <li>{experimentFormErrors.name}</li>}
                                        {experimentFormErrors.variants && <li>{experimentFormErrors.variants}</li>}
                                    </ol>
                                </LemonBanner>
                            )}
                    </div>
                </ToolbarMenu.Header>
                <ToolbarMenu.Body>
                    <div className="space-y-6 p-2">
                        <div className="flex w-full">
                            {selectedExperimentId === 'new' ? (
                                <div className="w-full">
                                    <LemonLabel>Name</LemonLabel>
                                    <LemonInput
                                        className="w-2/3"
                                        placeholder="Example: Pricing page conversion"
                                        onChange={(newName: string) => {
                                            experimentForm.name = newName
                                            setExperimentFormValue('name', experimentForm.name)
                                        }}
                                        value={experimentForm.name}
                                        status={experimentFormErrors.name ? 'danger' : 'default'}
                                    />
                                </div>
                            ) : (
                                <h4 className="col-span-2">{experimentForm.name}</h4>
                            )}
                        </div>
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <LemonLabel>Variants</LemonLabel>
                                {addVariantAvailable && (
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        icon={<IconPlus />}
                                        onClick={addNewVariant}
                                    >
                                        Add variant
                                    </LemonButton>
                                )}
                            </div>
                            <Group name="variants">
                                <div>
                                    <LemonCollapse
                                        size="medium"
                                        activeKey={selectedVariant}
                                        onChange={(newVariant) => {
                                            if (newVariant) {
                                                selectVariant(newVariant)
                                                applyVariant(newVariant)
                                            }
                                        }}
                                        panels={Object.keys(experimentForm.variants || {})
                                            .sort((a, b) => (b === 'control' ? 0 : a.localeCompare(b)))
                                            .map((variant) => {
                                                return {
                                                    key: variant,
                                                    header: <WebExperimentVariantHeader variant={variant} />,
                                                    content:
                                                        variant == 'control' ? (
                                                            <span className="m-2">
                                                                {' '}
                                                                The control variant represents your page in its original
                                                                state.{' '}
                                                            </span>
                                                        ) : (
                                                            <WebExperimentVariant variant={variant} />
                                                        ),
                                                }
                                            })}
                                    />
                                </div>
                            </Group>
                        </div>
                    </div>
                </ToolbarMenu.Body>
                <ToolbarMenu.Footer>
                    <div className="flex justify-between items-center w-full">
                        <LemonButton type="secondary" size="small" onClick={() => selectExperiment(null)}>
                            Cancel
                        </LemonButton>

                        <LemonButton type="primary" htmlType="submit" size="small">
                            {selectedExperimentId === 'new' ? 'Save as  draft' : 'Save experiment'}
                        </LemonButton>
                    </div>
                </ToolbarMenu.Footer>
            </Form>
        </ToolbarMenu>
    )
}
