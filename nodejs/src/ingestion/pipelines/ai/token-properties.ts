/**
 * Every token count the cost calculators read.
 *
 * Two places depend on knowing that set, which is why it lives in one:
 * `createValidateAiEventTokensStep` sanitizes each value before js-big-decimal
 * sees it, and `setCostsOnEvent` treats the presence of any one of them as the
 * provider having reported usage.
 *
 * Presence is what matters to the second, not value. `0` is a usage report that
 * says the model consumed nothing, while an absent property means the provider
 * never reported usage at all.
 *
 * Hand-maintained, so a calculator that starts reading a new token property has
 * to add it here too. Leave it out and an event carrying only that property
 * prices as unknown. Properties that modality extraction writes but no
 * calculator reads, such as `$ai_text_input_tokens`, do not belong here.
 */
export const TOKEN_COUNT_PROPERTIES = [
    '$ai_input_tokens',
    '$ai_output_tokens',
    '$ai_text_output_tokens',
    '$ai_reasoning_tokens',
    '$ai_cache_read_input_tokens',
    '$ai_cache_creation_input_tokens',
    '$ai_cache_creation_5m_input_tokens',
    '$ai_cache_creation_1h_input_tokens',
    '$ai_audio_input_tokens',
    '$ai_audio_output_tokens',
    '$ai_image_input_tokens',
    '$ai_image_output_tokens',
    '$ai_cache_read_audio_tokens',
] as const
