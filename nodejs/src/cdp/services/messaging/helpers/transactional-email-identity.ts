export type TransactionalEmailIdentity = {
    $email_template_id?: string
    $email_template_key?: string
}

/**
 * The names a sender uses for a transactional email in the send API: the template id, or the code-send key.
 * The workflow's email step keeps them in its config. A workflow saved before a name was stamped has neither,
 * so a missing name is left out, never sent as null.
 */
export const transactionalEmailIdentity = (
    config: { template_uuid?: unknown; template_key?: unknown } | null | undefined
): TransactionalEmailIdentity => ({
    ...(typeof config?.template_uuid === 'string' && config.template_uuid
        ? { $email_template_id: config.template_uuid }
        : {}),
    ...(typeof config?.template_key === 'string' && config.template_key
        ? { $email_template_key: config.template_key }
        : {}),
})
