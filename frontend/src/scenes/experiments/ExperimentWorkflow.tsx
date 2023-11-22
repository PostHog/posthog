import './Experiment.scss'

import clsx from 'clsx'
import { IconCheckmark, IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'
import { useState } from 'react'

export function ExperimentWorkflow(): JSX.Element {
    const [workflowValidateStepCompleted, setWorkflowValidateStepCompleted] = useState(false)
    const [workflowLaunchStepCompleted, setWorkflowLaunchStepCompleted] = useState(false)

    return (
        <>
            <div className="border rounded">
                <div className="card-secondary p-4 border-b">Experiment workflow</div>
                <div className="p-6 space-y-1.5">
                    <div className="flex">
                        <div className="exp-workflow-step rounded p-2 bg-primary-highlight w-full">
                            <div className="flex items-center">
                                <IconCheckmark className="text-xl text-primary" />
                                <b className="ml-2">Create experiment</b>
                            </div>
                            <div className="ml-8">Set variants, select participants, and add secondary metrics</div>
                        </div>
                    </div>
                    <div className="flex">
                        <div
                            className={clsx(
                                'w-full exp-workflow-step rounded p-2 cursor-pointer',
                                workflowValidateStepCompleted && 'bg-primary-highlight'
                            )}
                            onClick={() => setWorkflowValidateStepCompleted(!workflowValidateStepCompleted)}
                        >
                            <div className="flex items-center">
                                {workflowValidateStepCompleted ? (
                                    <IconCheckmark className="text-xl text-primary" />
                                ) : (
                                    <IconRadioButtonUnchecked className="text-xl" />
                                )}
                                <b className="ml-2">Validate experiment</b>
                            </div>
                            <div className="ml-8">
                                Once you've written your code, it's a good idea to test that each variant behaves as
                                you'd expect.
                            </div>
                        </div>
                    </div>
                    <div className="flex">
                        <div
                            className={clsx(
                                'w-full exp-workflow-step rounded p-2 cursor-pointer',
                                workflowLaunchStepCompleted && 'bg-primary-highlight'
                            )}
                            onClick={() => setWorkflowLaunchStepCompleted(!workflowLaunchStepCompleted)}
                        >
                            <div className="flex items-center">
                                {workflowLaunchStepCompleted ? (
                                    <IconCheckmark className="text-xl text-primary" />
                                ) : (
                                    <IconRadioButtonUnchecked className="text-xl" />
                                )}
                                <b className="ml-2">Launch experiment</b>
                            </div>
                            <div className="ml-8">
                                Run your experiment, monitor results, and decide when to terminate your experiment.
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </>
    )
}
