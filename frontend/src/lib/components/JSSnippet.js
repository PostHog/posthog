import React from 'react'
import { toast } from 'react-toastify'
import { CopyOutlined } from '@ant-design/icons'

export let JSSnippet = props => {
    let url = window.location.origin
    const copyRef = React.createRef()

    const copyToClipboard = str => {
        const el = document.createElement('textarea') // Create a <textarea> element
        el.value = str // Set its value to the string that you want copied
        el.setAttribute('readonly', '') // Make it readonly to be tamper-proof
        el.style.position = 'absolute'
        el.style.left = '-9999px' // Move outside the screen to make it invisible
        document.body.appendChild(el) // Append the <textarea> element to the HTML document
        el.select() // Select the <textarea> content
        document.execCommand('copy') // Copy - only works as a result of a user action (e.g. click events)
        document.body.removeChild(el) // Remove the <textarea> element
    }

    // Generated highlighted code html from http://hilite.me/ using the theme monokai
    // Converted to jsx using https://magic.reactjs.net/htmltojsx.htm
    // Add a <br/> and whitespace for the init to be in the nextline
    // Change the places where use the variables from user in the appropriate
    // Do not split this in multiple lines - messes with the whitespaces
    return (
        <div className="code-container">
            <CopyOutlined
                className="copy-icon"
                onClick={() => {
                    copyToClipboard(copyRef.current.innerText)
                    toast('Code Copied!')
                }}
            />
            <pre className="code scrolling-code" ref={copyRef}>
                {`<script>`}
                <br />
                &nbsp;&nbsp;
                <span style={{ color: '#f92672' }}>!</span>
                <span style={{ color: '#66d9ef' }}>function</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>){'{'}</span>
                <span style={{ color: '#66d9ef' }}>var</span> <span style={{ color: '#a6e22e' }}>o</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>n</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>p</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>r</span>
                <span style={{ color: '#f8f8f2' }}>;</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>__SV</span>
                <span style={{ color: '#f92672' }}>||</span>
                <span style={{ color: '#f8f8f2' }}>(window.</span>
                <span style={{ color: '#a6e22e' }}>posthog</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>_i</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#f8f8f2' }}>[],</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>init</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#66d9ef' }}>function</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>i</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>s</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>a</span>
                <span style={{ color: '#f8f8f2' }}>){'{'}</span>
                <span style={{ color: '#66d9ef' }}>function</span> <span style={{ color: '#a6e22e' }}>g</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>){'{'}</span>
                <span style={{ color: '#66d9ef' }}>var</span> <span style={{ color: '#a6e22e' }}>o</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>split</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#e6db74' }}>"."</span>
                <span style={{ color: '#f8f8f2' }}>);</span>
                <span style={{ color: '#ae81ff' }}>2</span>
                <span style={{ color: '#f92672' }}>==</span>
                <span style={{ color: '#a6e22e' }}>o</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>length</span>
                <span style={{ color: '#f92672' }}>&amp;&amp;</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f8f8f2' }}>[</span>
                <span style={{ color: '#a6e22e' }}>o</span>
                <span style={{ color: '#f8f8f2' }}>[</span>
                <span style={{ color: '#ae81ff' }}>0</span>
                <span style={{ color: '#f8f8f2' }}>]],</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>o</span>
                <span style={{ color: '#f8f8f2' }}>[</span>
                <span style={{ color: '#ae81ff' }}>1</span>
                <span style={{ color: '#f8f8f2' }}>]),</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f8f8f2' }}>[</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>]</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#66d9ef' }}>function</span>
                <span style={{ color: '#f8f8f2' }}>(){'{'}</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>push</span>
                <span style={{ color: '#f8f8f2' }}>([</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>].</span>
                <span style={{ color: '#a6e22e' }}>concat</span>
                <span style={{ color: '#f8f8f2' }}>(Array.</span>
                <span style={{ color: '#a6e22e' }}>prototype</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>slice</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>call</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>arguments</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#ae81ff' }}>0</span>
                <span style={{ color: '#f8f8f2' }}>
                    ))){'}'}
                    {'}'}(
                </span>
                <span style={{ color: '#a6e22e' }}>p</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>createElement</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#e6db74' }}>"script"</span>
                <span style={{ color: '#f8f8f2' }}>)).</span>
                <span style={{ color: '#a6e22e' }}>type</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#e6db74' }}>"text/javascript"</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>p</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>async</span>
                <span style={{ color: '#f92672' }}>=!</span>
                <span style={{ color: '#ae81ff' }}>0</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>p</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>src</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>s</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>api_host</span>
                <span style={{ color: '#f92672' }}>+</span>
                <span style={{ color: '#e6db74' }}>"/static/array.js"</span>
                <span style={{ color: '#f8f8f2' }}>,(</span>
                <span style={{ color: '#a6e22e' }}>r</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>getElementsByTagName</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#e6db74' }}>"script"</span>
                <span style={{ color: '#f8f8f2' }}>)[</span>
                <span style={{ color: '#ae81ff' }}>0</span>
                <span style={{ color: '#f8f8f2' }}>]).</span>
                <span style={{ color: '#a6e22e' }}>parentNode</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>insertBefore</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>p</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>r</span>
                <span style={{ color: '#f8f8f2' }}>);</span>
                <span style={{ color: '#66d9ef' }}>var</span> <span style={{ color: '#a6e22e' }}>u</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>;</span>
                <span style={{ color: '#66d9ef' }}>for</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#66d9ef' }}>void</span> <span style={{ color: '#ae81ff' }}>0</span>
                <span style={{ color: '#f92672' }}>!==</span>
                <span style={{ color: '#a6e22e' }}>a</span>
                <span style={{ color: '#f92672' }}>?</span>
                <span style={{ color: '#a6e22e' }}>u</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>[</span>
                <span style={{ color: '#a6e22e' }}>a</span>
                <span style={{ color: '#f8f8f2' }}>]</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#f8f8f2' }}>[]</span>
                <span style={{ color: '#f92672' }}>:</span>
                <span style={{ color: '#a6e22e' }}>a</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#e6db74' }}>"posthog"</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>u</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>people</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#a6e22e' }}>u</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>people</span>
                <span style={{ color: '#f92672' }}>||</span>
                <span style={{ color: '#f8f8f2' }}>[],</span>
                <span style={{ color: '#a6e22e' }}>u</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>toString</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#66d9ef' }}>function</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f8f8f2' }}>){'{'}</span>
                <span style={{ color: '#66d9ef' }}>var</span> <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#e6db74' }}>"posthog"</span>
                <span style={{ color: '#f8f8f2' }}>;</span>
                <span style={{ color: '#66d9ef' }}>return</span>
                <span style={{ color: '#e6db74' }}>"posthog"</span>
                <span style={{ color: '#f92672' }}>!==</span>
                <span style={{ color: '#a6e22e' }}>a</span>
                <span style={{ color: '#f92672' }}>&amp;&amp;</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f92672' }}>+=</span>
                <span style={{ color: '#e6db74' }}>"."</span>
                <span style={{ color: '#f92672' }}>+</span>
                <span style={{ color: '#a6e22e' }}>a</span>
                <span style={{ color: '#f8f8f2' }}>),</span>
                <span style={{ color: '#a6e22e' }}>t</span>
                <span style={{ color: '#f92672' }}>||</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f92672' }}>+=</span>
                <span style={{ color: '#e6db74' }}>" (stub)"</span>
                <span style={{ color: '#f8f8f2' }}>),</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>{'}'},</span>
                <span style={{ color: '#a6e22e' }}>u</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>people</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>toString</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#66d9ef' }}>function</span>
                <span style={{ color: '#f8f8f2' }}>(){'{'}</span>
                <span style={{ color: '#66d9ef' }}>return</span> <span style={{ color: '#a6e22e' }}>u</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>toString</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#ae81ff' }}>1</span>
                <span style={{ color: '#f8f8f2' }}>)</span>
                <span style={{ color: '#f92672' }}>+</span>
                <span style={{ color: '#e6db74' }}>".people (stub)"</span>
                <span style={{ color: '#f8f8f2' }}>{'}'},</span>
                <span style={{ color: '#a6e22e' }}>o</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#e6db74' }}>
                    "capture identify alias people.set people.set_once set_config register register_once unregister
                    opt_out_capturing has_opted_out_capturing opt_in_capturing reset"
                </span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>split</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#e6db74' }}>" "</span>
                <span style={{ color: '#f8f8f2' }}>),</span>
                <span style={{ color: '#a6e22e' }}>n</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#ae81ff' }}>0</span>
                <span style={{ color: '#f8f8f2' }}>;</span>
                <span style={{ color: '#a6e22e' }}>n</span>
                <span style={{ color: '#f92672' }}>&lt;</span>
                <span style={{ color: '#a6e22e' }}>o</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>length</span>
                <span style={{ color: '#f8f8f2' }}>;</span>
                <span style={{ color: '#a6e22e' }}>n</span>
                <span style={{ color: '#f92672' }}>++</span>
                <span style={{ color: '#f8f8f2' }}>)</span>
                <span style={{ color: '#a6e22e' }}>g</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#a6e22e' }}>u</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>o</span>
                <span style={{ color: '#f8f8f2' }}>[</span>
                <span style={{ color: '#a6e22e' }}>n</span>
                <span style={{ color: '#f8f8f2' }}>]);</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>_i</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>push</span>
                <span style={{ color: '#f8f8f2' }}>([</span>
                <span style={{ color: '#a6e22e' }}>i</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>s</span>
                <span style={{ color: '#f8f8f2' }}>,</span>
                <span style={{ color: '#a6e22e' }}>a</span>
                <span style={{ color: '#f8f8f2' }}>]){'}'},</span>
                <span style={{ color: '#a6e22e' }}>e</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>__SV</span>
                <span style={{ color: '#f92672' }}>=</span>
                <span style={{ color: '#ae81ff' }}>1</span>
                <span style={{ color: '#f8f8f2' }}>){'}'}(document,window.</span>
                <span style={{ color: '#a6e22e' }}>posthog</span>
                <span style={{ color: '#f92672' }}>||</span>
                <span style={{ color: '#f8f8f2' }}>[]);</span>
                <br />
                &nbsp;&nbsp;
                <span style={{ color: '#a6e22e' }}>posthog</span>
                <span style={{ color: '#f8f8f2' }}>.</span>
                <span style={{ color: '#a6e22e' }}>init</span>
                <span style={{ color: '#f8f8f2' }}>(</span>
                <span style={{ color: '#e6db74' }}>{`'${props.user.team.api_token}'`}</span>
                <span style={{ color: '#f8f8f2' }}>,</span> <span style={{ color: '#f8f8f2' }}>{'{'}</span>
                <span style={{ color: '#a6e22e' }}>api_host</span>
                <span style={{ color: '#f92672' }}>:</span> <span style={{ color: '#e6db74' }}>{`'${url}'`}</span>
                <span style={{ color: '#f8f8f2' }}>{'}'})</span>
                <br />
                {`</script>`}
                <br />
            </pre>
        </div>
    )
}
