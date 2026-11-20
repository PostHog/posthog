import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import {
    Autocomplete,
    AutocompleteContent,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteList,
    Button,
    Field,
    FieldError,
    FieldLabel,
} from '@posthog/quill'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import type { LoadTags } from 'lib/components/tagSelectLogic'

import { projectTagsLogic } from './projectTagsLogic'

const PROJECT_GROUP_MAX_LENGTH = 200

export function QuillProjectTags({ regularTagSource }: { regularTagSource: LoadTags }): JSX.Element {
    const {
        currentProjectLoading,
        regularTags,
        canEditProjectGroup,
        projectGroup,
        projectGroupTagChanged,
        projectGroupOptions,
        projectGroupValidationErrors,
        projectGroupHasErrors,
        isProjectGroupSubmitting,
    } = useValues(projectTagsLogic)
    const { updateTags, setProjectGroupValue } = useActions(projectTagsLogic)
    const projectGroupInputId = useId()

    const optionLabels = Object.fromEntries(projectGroupOptions.map((option) => [option.value, option.label]))
    const projectGroupError = projectGroupValidationErrors.name

    return (
        <div className="flex flex-col gap-3">
            <ObjectTags
                tags={regularTags}
                loadTags={regularTagSource}
                onChange={updateTags}
                saving={currentProjectLoading}
                data-attr="project-tags"
            />
            {canEditProjectGroup && (
                <Form logic={projectTagsLogic} formKey="projectGroup" enableFormOnSubmit className="max-w-80">
                    <Field data-invalid={projectGroupError ? true : undefined}>
                        <FieldLabel htmlFor={projectGroupInputId}>Project group</FieldLabel>
                        <div className="flex gap-1">
                            <Autocomplete
                                items={projectGroupOptions.map((option) => option.value)}
                                value={projectGroup.name}
                                onValueChange={(name: string) => setProjectGroupValue('name', name)}
                            >
                                <AutocompleteInput
                                    id={projectGroupInputId}
                                    className="flex-1"
                                    showSearchIcon={false}
                                    maxLength={PROJECT_GROUP_MAX_LENGTH}
                                    disabled={currentProjectLoading || isProjectGroupSubmitting}
                                    placeholder="For example, production apps"
                                    data-attr="project-group-input"
                                />
                                <AutocompleteContent>
                                    <AutocompleteList>
                                        {(value: string) => (
                                            <AutocompleteItem key={value} value={value}>
                                                {optionLabels[value] ?? value}
                                            </AutocompleteItem>
                                        )}
                                    </AutocompleteList>
                                </AutocompleteContent>
                            </Autocomplete>
                            <Button
                                variant="primary"
                                type="submit"
                                disabledReason={
                                    !projectGroupTagChanged
                                        ? 'No changes to save'
                                        : projectGroupHasErrors
                                          ? (projectGroupError ?? 'Fix the project group first')
                                          : undefined
                                }
                                loading={currentProjectLoading || isProjectGroupSubmitting}
                                data-attr="project-group-save"
                            >
                                Save
                            </Button>
                        </div>
                        {projectGroupError && <FieldError>{projectGroupError}</FieldError>}
                    </Field>
                </Form>
            )}
        </div>
    )
}
