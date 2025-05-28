import { LemonButton, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { capitalizeFirstLetter } from 'lib/utils'
import { useCallback, useEffect, useMemo } from 'react'
import EmailEditor from 'react-email-editor'

import { emailTemplaterLogic, EmailTemplaterLogicProps } from './emailTemplaterLogic'
import { MergeTagsModal } from './MergeTagsModal'

/*
const engine = useMemo(() => new Liquid({
    // you can register custom tags/filters here
  }), [])
*/

function EmailTemplaterForm({
    mode,
    emailMetaFields,
    ...props
}: EmailTemplaterLogicProps & {
    mode: 'full' | 'preview'
}): JSX.Element {
    const { setEmailEditorRef, emailEditorReady, setIsModalOpen, applyTemplate, setIsMergeTagsModalOpen } = useActions(
        emailTemplaterLogic(props)
    )
    const { appliedTemplate, templates, templatesLoading, isMergeTagsModalOpen } = useValues(emailTemplaterLogic(props))

    const { featureFlags } = useValues(featureFlagLogic)
    const isMessagingTemplatesEnabled = featureFlags[FEATURE_FLAGS.MESSAGING_LIBRARY]

    // Available merge tags based on globals - memoize with stable dependencies
    const availableMergeTags = useMemo(() => {
        const tags = []

        // Add customer properties
        if (props.globals?.customer) {
            Object.keys(props.globals.customer).forEach((key) => {
                tags.push({
                    label: `Customer ${capitalizeFirstLetter(key.replace(/_/g, ' '))}`,
                    value: `{{ customer.${key} }}`,
                    category: 'Customer',
                })
            })
        }

        // Add common merge tags
        tags.push(
            { label: 'Current Date', value: '{{ "now" | date: "%Y-%m-%d" }}', category: 'Date/Time' },
            { label: 'Current Time', value: '{{ "now" | date: "%H:%M" }}', category: 'Date/Time' },
            { label: 'Current Year', value: '{{ "now" | date: "%Y" }}', category: 'Date/Time' }
        )

        return tags
    }, [JSON.stringify(props.globals?.customer)]) // Use JSON.stringify for stable comparison

    // Custom JS for merge tags functionality - only regenerate when tags actually change
    const customJS = useMemo(() => {
        return `
// Function to open merge tags modal
window.openMergeTagsModal = function() {
  window.dispatchEvent(new CustomEvent('openMergeTagsModal'));
};

// Register custom property editor for merge tag selection
unlayer.registerPropertyEditor({
  name: 'merge_tag_selector',
  Widget: unlayer.createWidget({
    render(value, updateValue, data) {
      return \`
        <div>
          <input type="text" value="\${value || ''}" class="merge-tag-input" style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 8px;" placeholder="Enter merge tag..." />
          <button class="select-merge-tag-btn" style="width: 100%; padding: 8px; background: #1976d2; color: white; border: none; border-radius: 4px; cursor: pointer;">Select from List</button>
        </div>
      \`;
    },
    mount(node, value, updateValue, data) {
      const input = node.querySelector('.merge-tag-input');
      const button = node.querySelector('.select-merge-tag-btn');
      
      input.addEventListener('input', function(e) {
        updateValue(e.target.value);
      });
      
      button.addEventListener('click', function() {
        window.currentUpdateValue = updateValue;
        window.openMergeTagsModal();
      });
    },
  }),
});

// Register merge tags tool
unlayer.registerTool({
  name: 'merge_tag',
  label: 'Merge Tag',
  icon: 'fa-tags',
  supportedDisplayModes: ['email'],
  options: {
    default: {
      title: null,
    },
    content: {
      title: 'Merge Tag',
      position: 1,
      options: {
        tagValue: {
          label: 'Tag Value',
          defaultValue: '{{ customer.email }}',
          widget: 'merge_tag_selector',
        },
      },
    },
  },
  values: {
    tagValue: '{{ customer.email }}',
  },
  renderer: {
    Viewer: unlayer.createViewer({
      render(values) {
        const tag = values.tagValue || '{{ merge.tag }}';
        return \`<span style="background-color: #e3f2fd; color: #1976d2; padding: 2px 6px; border-radius: 3px; font-family: monospace; border: 1px solid #bbdefb; display: inline-block;">\${tag}</span>\`;
      },
    }),
    exporters: {
      email: function (values) {
        return values.tagValue || '{{ merge.tag }}';
      },
    },
    head: {
      css: function (values) {},
      js: function (values) {},
    },
  },
});
        `
    }, []) // Empty dependency array since this doesn't depend on dynamic data

    // Set up event listener for merge tags modal - use useCallback to prevent recreation
    const handleOpenMergeTagsModal = useCallback(() => {
        setIsMergeTagsModalOpen(true)
    }, [setIsMergeTagsModalOpen])

    useEffect(() => {
        window.addEventListener('openMergeTagsModal', handleOpenMergeTagsModal)

        return () => {
            window.removeEventListener('openMergeTagsModal', handleOpenMergeTagsModal)
        }
    }, [handleOpenMergeTagsModal])

    // Memoize email editor options to prevent unnecessary re-renders
    const emailEditorOptions = useMemo(
        () => ({
            customJS: [`data:text/javascript;base64,${btoa(customJS)}`],
        }),
        [customJS]
    )

    return (
        <>
            {isMessagingTemplatesEnabled && templates.length > 0 && (
                <LemonSelect
                    className="mb-2"
                    placeholder="Start from a template (optional)"
                    loading={templatesLoading}
                    value={appliedTemplate?.id}
                    options={templates.map((template) => ({
                        label: template.name,
                        value: template.id,
                    }))}
                    onChange={(id) => {
                        const template = templates.find((t) => t.id === id)
                        if (template) {
                            applyTemplate(template)
                        }
                    }}
                    data-attr="email-template-selector"
                />
            )}
            <Form
                className="flex flex-col border rounded overflow-hidden flex-1"
                logic={props.formLogic}
                props={props.formLogicProps}
                formKey={props.formKey}
            >
                {(emailMetaFields || ['from', 'to', 'subject']).map((field) => (
                    <LemonField
                        key={field}
                        name={`${props.formFieldsPrefix ? props.formFieldsPrefix + '.' : ''}${field}`}
                        className="border-b shrink-0 gap-1 pl-2"
                        // We will handle the error display ourselves
                        renderError={() => null}
                    >
                        {({ value, onChange, error }) => (
                            <div className="flex items-center">
                                <LemonLabel className={error ? 'text-danger' : ''}>
                                    {capitalizeFirstLetter(field)}
                                </LemonLabel>
                                <CodeEditorInline
                                    embedded
                                    className="flex-1"
                                    globals={props.globals}
                                    value={value}
                                    onChange={onChange}
                                />
                            </div>
                        )}
                    </LemonField>
                ))}

                {mode === 'full' ? (
                    <EmailEditor
                        ref={(r) => setEmailEditorRef(r)}
                        onReady={() => emailEditorReady()}
                        options={emailEditorOptions}
                    />
                ) : (
                    <LemonField
                        name={`${props.formFieldsPrefix ? props.formFieldsPrefix + '.' : ''}html`}
                        className="relative flex flex-col"
                    >
                        {({ value }) => (
                            <>
                                <div className="absolute inset-0 p-2 flex items-end justify-center transition-opacity opacity-0 hover:opacity-100">
                                    <div className="opacity-50 bg-surface-primary absolute inset-0" />
                                    <LemonButton type="primary" size="small" onClick={() => setIsModalOpen(true)}>
                                        Click to modify content
                                    </LemonButton>
                                </div>

                                <iframe srcDoc={value} className="flex-1" />
                            </>
                        )}
                    </LemonField>
                )}
            </Form>

            <MergeTagsModal
                isOpen={isMergeTagsModalOpen}
                onClose={() => setIsMergeTagsModalOpen(false)}
                mergeTags={availableMergeTags}
                onSelectTag={(tag) => {
                    // Update the current property editor if available
                    if (window.currentUpdateValue) {
                        window.currentUpdateValue(tag.value)
                        window.currentUpdateValue = null
                    }
                    setIsMergeTagsModalOpen(false)
                }}
            />
        </>
    )
}

export function EmailTemplaterModal({ ...props }: EmailTemplaterLogicProps): JSX.Element {
    const { isModalOpen } = useValues(emailTemplaterLogic(props))
    const { setIsModalOpen, onSave } = useActions(emailTemplaterLogic(props))

    return (
        <LemonModal isOpen={isModalOpen} width="90vw" onClose={() => setIsModalOpen(false)}>
            <div className="h-[80vh] flex">
                <div className="flex flex-col flex-1">
                    <div className="shrink-0">
                        <h2>Editing email template</h2>
                    </div>
                    <EmailTemplaterForm {...props} mode="full" />
                    <div className="flex items-center mt-2 gap-2">
                        <div className="flex-1" />
                        <LemonButton onClick={() => setIsModalOpen(false)}>Cancel</LemonButton>
                        <LemonButton type="primary" onClick={() => onSave()}>
                            Save
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}

export function EmailTemplater(props: EmailTemplaterLogicProps): JSX.Element {
    return (
        <div className="flex flex-col flex-1">
            <EmailTemplaterForm {...props} mode="preview" />
            <EmailTemplaterModal {...props} />
        </div>
    )
}
