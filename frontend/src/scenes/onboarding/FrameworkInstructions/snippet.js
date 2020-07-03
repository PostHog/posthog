import React from 'react'
import { toast } from 'react-toastify'
import { CopyOutlined } from '@ant-design/icons'

export default function Snippet(props) {
    const copyRef = React.createRef()

    const copyToClipboard = (str) => {
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
                {props.children}
            </pre>
        </div>
    )
}
