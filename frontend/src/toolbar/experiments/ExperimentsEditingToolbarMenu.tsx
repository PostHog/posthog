import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
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
            inspectForElementWithIndex('test', 0)
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
                    <div>
                        <div className="flex w-full m-1">
                            {selectedExperimentId === 'new' ? (
                                <>
                                    <LemonInput
                                        placeholder="Enter experiment name"
                                        onChange={(newName: string) => {
                                            experimentForm.name = newName
                                            setExperimentFormValue('name', experimentForm.name)
                                        }}
                                        value={experimentForm.name}
                                        status={experimentFormErrors.name ? 'danger' : 'default'}
                                    />
                                </>
                            ) : (
                                <h4 className="col-span-2">{experimentForm.name}</h4>
                            )}
                        </div>
                        <Group name="variants">
                            <div>
                                <LemonCollapse
                                    size="medium"
                                    activeKey={selectedVariant}
                                    onChange={(variant) => {
                                        if (variant) {
                                            selectVariant(variant)
                                            applyVariant(selectedVariant, variant)
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
                        {addVariantAvailable && (
                            <div className="grid grid-cols-3 mt-2 mb-1">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    className="col-span-1"
                                    sideIcon={<IconPlus />}
                                    onClick={addNewVariant}
                                >
                                    Add variant
                                </LemonButton>
                            </div>
                        )}
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
