export type TransactionalEmailIdentity = {
    $email_template_id?: string
    $email_template_key?: string
}

export const transactionalEmailIdentity = (
    config: { template_uuid?: unknown; template_key?: unknown } | undefined
): TransactionalEmailIdentity => ({
    ...(typeof config?.template_uuid === 'string' && config.template_uuid
        ? { $email_template_id: config.template_uuid }
        : {}),
    ...(typeof config?.template_key === 'string' && config.template_key
        ? { $email_template_key: config.template_key }
        : {}),
})
