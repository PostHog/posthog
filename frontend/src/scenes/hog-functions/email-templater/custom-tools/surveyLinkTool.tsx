// Unlayer custom tool that inserts a hosted-survey link into an email body.
// Auto-appends a `distinct_id` (or `email`) query param so the response is tied
// back to the recipient when the survey is loaded.

export const surveyLinkToolCustomJs = `
unlayer.registerTool({
    name: 'posthog_survey_link',
    label: 'Survey link',
    icon: 'fa-poll',
    supportedDisplayModes: ['email'],
    position: 16,
    options: {
        survey: {
            title: 'Hosted survey',
            position: 1,
            collapsed: false,
            options: {
                survey_url: {
                    label: 'Survey URL',
                    defaultValue: '',
                    widget: 'text',
                },
                link_text: {
                    label: 'Link text',
                    defaultValue: 'Take the survey',
                    widget: 'text',
                },
                identify_by: {
                    label: 'Identify respondent by',
                    defaultValue: 'distinct_id',
                    widget: 'dropdown',
                    data: {
                        options: [
                            { label: 'Person distinct ID (recommended)', value: 'distinct_id' },
                            { label: 'Person email', value: 'email' },
                            { label: 'Do not identify', value: 'none' },
                        ],
                    },
                },
                prefill_query: {
                    label: 'Pre-fill answers (optional)',
                    defaultValue: '',
                    widget: 'text',
                    helperText: 'e.g. q0=5 to pre-answer the first question with rating 5',
                },
            },
        },
        appearance: {
            title: 'Appearance',
            position: 2,
            collapsed: true,
            options: {
                style: {
                    label: 'Style',
                    defaultValue: 'button',
                    widget: 'dropdown',
                    data: {
                        options: [
                            { label: 'Button', value: 'button' },
                            { label: 'Text link', value: 'link' },
                        ],
                    },
                },
                button_color: {
                    label: 'Button background',
                    defaultValue: '#1d4aff',
                    widget: 'color_picker',
                },
                text_color: {
                    label: 'Text color',
                    defaultValue: '#ffffff',
                    widget: 'color_picker',
                },
            },
        },
    },
    values: {},
    renderer: {
        Viewer: unlayer.createViewer({
            render(values) {
                return renderSurveyLink(values)
            },
        }),
        exporters: {
            email: function (values) {
                return renderSurveyLink(values)
            },
        },
    },
})

function renderSurveyLink(values) {
    var rawUrl = (values.survey_url || '').trim()
    var linkText = (values.link_text || 'Take the survey').trim()
    var identifyBy = values.identify_by || 'distinct_id'
    var prefill = (values.prefill_query || '').trim().replace(/^[?&]+/, '')
    var style = values.style || 'button'
    var buttonColor = values.button_color || '#1d4aff'
    var textColor = values.text_color || '#ffffff'

    if (!rawUrl) {
        return '<div style="padding:12px;border:1px dashed #ccc;color:#888;font-family:Arial,sans-serif;font-size:14px;">' +
            'Paste a hosted survey URL in the sidebar to render the link.' +
            '</div>'
    }

    var params = []
    if (identifyBy === 'distinct_id') {
        params.push('distinct_id={{ person.properties.distinct_id }}')
    } else if (identifyBy === 'email') {
        params.push('email={{ person.properties.email }}')
    }
    if (prefill) {
        params.push(prefill)
    }
    var separator = rawUrl.indexOf('?') === -1 ? '?' : '&'
    var href = params.length ? rawUrl + separator + params.join('&') : rawUrl

    if (style === 'link') {
        return '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:140%;">' +
            '<a href="' + href + '" style="color:' + buttonColor + ';text-decoration:underline;">' +
            linkText +
            '</a></div>'
    }

    return '<div style="text-align:left;font-family:Arial,sans-serif;">' +
        '<a href="' + href + '" ' +
        'style="display:inline-block;padding:10px 18px;background-color:' + buttonColor +
        ';color:' + textColor + ';text-decoration:none;border-radius:6px;font-size:14px;font-weight:500;">' +
        linkText +
        '</a></div>'
}
`
