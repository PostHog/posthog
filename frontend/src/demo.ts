import posthog from './lib/posthog-typed'

// ✅ SUCCESS: All properties provided
posthog.typed.downloaded_file({
    file_name: 'report.pdf',
    file_size_b: 1024000,
    file_type: 'application/pdf',
})

// ✅ SUCCESS: Only required property
posthog.typed.downloaded_file({
    file_size_b: 512000,
})

// ✅ SUCCESS: Unknown property 'download_speed'
posthog.typed.downloaded_file({
    file_size_b: 2048000,
    download_speed: 'fast',
})

// ❌ ERROR: Missing required property 'file_size_b'
posthog.typed.downloaded_file({
    file_name: 'data.csv',
})

// ❌ ERROR: Wrong type for file_size_b (string instead of number)
posthog.typed.downloaded_file({
    file_size_b: '1024000',
})
