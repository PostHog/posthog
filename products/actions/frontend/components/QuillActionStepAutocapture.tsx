import { useState } from 'react'

import { IconExternal } from '@posthog/icons'
import {
    Button,
    Credenza,
    CredenzaBody,
    CredenzaClose,
    CredenzaContent,
    CredenzaDescription,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
} from '@posthog/quill'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { OperandTag } from 'lib/components/PropertyFilters/components/OperandTag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ActionStepType } from '~/types'

import { withActionStepOption } from '../utils/actionStepEdits'
import { QuillActionStepField } from './QuillActionStepField'
import { QuillActionStepMatchedField } from './QuillActionStepMatchedField'

const LEARN_MORE_URL = 'https://posthog.com/docs/data/actions?utm_medium=in-product&utm_campaign=action-page'

function AndSeparator(): JSX.Element {
    return (
        <div className="flex w-full justify-center">
            <OperandTag operand="and" />
        </div>
    )
}

export function QuillActionStepAutocapture({
    step,
    actionId,
    sendStep,
    disabledReason,
}: {
    step: ActionStepType
    actionId: number
    sendStep: (step: ActionStepType) => void
    disabledReason?: string
}): JSX.Element {
    const [selectingElement, setSelectingElement] = useState(false)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" onClick={() => setSelectingElement(true)} disabledReason={disabledReason}>
                    Select element on site
                    <IconExternal />
                </Button>
                <Button
                    variant="link"
                    size="inline"
                    render={<LinkPrimitive to={`${LEARN_MORE_URL}#1-autocapture`} target="_blank" />}
                >
                    See documentation.
                </Button>
            </div>
            <QuillActionStepMatchedField
                step={step}
                sendStep={sendStep}
                field="text"
                label="Element text"
                disabledReason={disabledReason}
            />
            <AndSeparator />
            <QuillActionStepMatchedField
                step={step}
                sendStep={sendStep}
                field="href"
                label="Element link target"
                caption={
                    <>
                        Filtering by the <code>href</code> attribute. Only <code>{'<a/>'}</code> elements will be
                        matched.
                    </>
                }
                disabledReason={disabledReason}
            />
            {step.tag_name ? (
                <>
                    <AndSeparator />
                    <QuillActionStepField
                        label="Element matches tag name"
                        caption="Filtering by the tag name of the element. This field is deprecated and superseded by the HTML selector below. We recommend adding the tag name to the HTML selector field instead. This field will disappear when cleared."
                        value={step.tag_name}
                        onChange={(value) => sendStep(withActionStepOption(step, 'tag_name', value))}
                        disabledReason={disabledReason}
                    />
                </>
            ) : null}
            <AndSeparator />
            <QuillActionStepField
                label="Element matches HTML selector"
                caption={
                    <>
                        The selector can be a tag name, class, HTML attribute, or all of those combined. Example:{' '}
                        <code>button[data-attr="signup"]</code>.{' '}
                        <Button
                            variant="link"
                            size="inline"
                            render={<LinkPrimitive to={`${LEARN_MORE_URL}#matching-selectors`} />}
                        >
                            Learn more in Docs.
                        </Button>
                    </>
                }
                value={step.selector || ''}
                onChange={(value) => sendStep(withActionStepOption(step, 'selector', value))}
                disabledReason={disabledReason}
            />
            <AndSeparator />
            <QuillActionStepMatchedField
                step={step}
                sendStep={sendStep}
                field="url"
                label="Page URL"
                caption="The page on which the interaction occurred."
                disabledReason={disabledReason}
            />
            <Credenza open={selectingElement} onOpenChange={setSelectingElement}>
                <CredenzaContent>
                    <CredenzaHeader>
                        <CredenzaTitle>Select an element</CredenzaTitle>
                        <CredenzaDescription>
                            {actionId
                                ? 'Choose the domain on which to edit this action'
                                : 'Choose the domain on which to create this action'}
                        </CredenzaDescription>
                    </CredenzaHeader>
                    <CredenzaBody>
                        <AuthorizedUrlList actionId={actionId} type={AuthorizedUrlListType.TOOLBAR_URLS} />
                    </CredenzaBody>
                    <CredenzaFooter>
                        <CredenzaClose render={<Button variant="outline" />}>Close</CredenzaClose>
                    </CredenzaFooter>
                </CredenzaContent>
            </Credenza>
        </div>
    )
}
