import { IconCode } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

function getSurveyUrl(surveyId: string): string {
    const url = new URL(window.location.origin)
    url.pathname = `/external_surveys/${surveyId}`
    return url.toString()
}

function getEmbedSnippet(surveyId: string): string {
    const surveyUrl = getSurveyUrl(surveyId)
    return `<div id="posthog-survey-container-${surveyId}"></div>
<script>
  (function() {
    var container = document.getElementById('posthog-survey-container-${surveyId}');
    var iframe = document.createElement('iframe');
    iframe.id = 'posthog-survey-${surveyId}';
    iframe.width = '100%';
    iframe.frameBorder = '0';
    iframe.style.cssText = 'border: none; border-radius: 12px; max-width: 720px;';

    var baseUrl = '${surveyUrl}?embed=true';

    function loadSurvey() {
      var url = baseUrl;
      var distinctId = window.posthog?.get_distinct_id?.();
      if (distinctId) {
        url += '&distinct_id=' + encodeURIComponent(distinctId);
      }
      iframe.src = url;
      container.appendChild(iframe);
    }

    if (window.posthog?.onFeatureFlags) {
      window.posthog.onFeatureFlags(loadSurvey);
    } else {
      loadSurvey();
    }

    window.addEventListener('message', function(e) {
      if (e.origin !== '${new URL(surveyUrl).origin}') return;
      if (e.data.type === 'posthog:survey:height' && e.data.surveyId === '${surveyId}') {
        var height = parseInt(e.data.height, 10);
        if (height > 0 && height < 10000) {
          iframe.style.height = height + 'px';
        }
      }
    });
  })();
</script>`
}

export function CopySurveyLink({
    surveyId,
    enableIframeEmbedding,
    className,
}: {
    surveyId: string
    enableIframeEmbedding?: boolean
    className?: string
}): JSX.Element {
    return (
        <div className={`flex flex-row gap-2 ${className ?? ''}`}>
            <LemonButton
                icon={<IconLink />}
                onClick={() => {
                    copyToClipboard(getSurveyUrl(surveyId), 'survey link')
                }}
                size="small"
                tooltip="Responses are anonymous. Add the distinct_id query parameter to identify respondents."
            >
                Copy URL
            </LemonButton>
            {enableIframeEmbedding && (
                <LemonButton
                    icon={<IconCode />}
                    onClick={() => {
                        copyToClipboard(getEmbedSnippet(surveyId), 'embed code')
                    }}
                    size="small"
                    tooltip="Copy HTML snippet to embed this survey in an iframe"
                >
                    Copy embed code
                </LemonButton>
            )}
        </div>
    )
}
