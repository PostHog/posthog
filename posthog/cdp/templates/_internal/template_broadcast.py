from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template_new_broadcast: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    free=True,
    type="broadcast",
    id="template-new-broadcast",
    name="Hello !",
    description="This is a broadcast",
    icon_url="/static/hedgehog/explorer-hog.png",
    category=["Email Marketing"],
    hog="""sendEmail(inputs)""".strip(),
    inputs_schema=[
        {
            "key": "email",
            "type": "email",
            "label": "Email",
            "default": {
                "to": "{person.properties.email}",
                "body": "Hello {person.properties.first_name} {person.properties.last_name}!\n\nThis is a broadcast",
                "from": "info@posthog.com",
                "subject": "Hello {person.properties.email}",
                "html": '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional //EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd"><html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><head>\n<!--[if gte mso 9]>\n<xml>\n  <o:OfficeDocumentSettings>\n    <o:AllowPNG/>\n    <o:PixelsPerInch>96</o:PixelsPerInch>\n  </o:OfficeDocumentSettings>\n</xml>\n<![endif]-->\n  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n  <meta name="x-apple-disable-message-reformatting" />\n  <!--[if !mso]><!--><meta http-equiv="X-UA-Compatible" content="IE=edge" /><!--<![endif]-->\n  <title></title>\n  \n    <style type="text/css">\n      \n      @media only screen and (min-width: 520px) \\{\n        .u-row \\{\n          width: 500px !important;\n        }\n\n        .u-row .u-col \\{\n          vertical-align: top;\n        }\n\n        \n            .u-row .u-col-100 \\{\n              width: 500px !important;\n            }\n          \n      }\n\n      @media only screen and (max-width: 520px) \\{\n        .u-row-container \\{\n          max-width: 100% !important;\n          padding-left: 0px !important;\n          padding-right: 0px !important;\n        }\n\n        .u-row \\{\n          width: 100% !important;\n        }\n\n        .u-row .u-col \\{\n          display: block !important;\n          width: 100% !important;\n          min-width: 320px !important;\n          max-width: 100% !important;\n        }\n\n        .u-row .u-col &gt; div \\{\n          margin: 0 auto;\n        }\n\n\n}\n    \nbody \\{\n  margin: 0;\n  padding: 0;\n}\n\ntable,\ntr,\ntd \\{\n  vertical-align: top;\n  border-collapse: collapse;\n}\n\np \\{\n  margin: 0;\n}\n\n.ie-container table,\n.mso-container table \\{\n  table-layout: fixed;\n}\n\n* \\{\n  line-height: inherit;\n}\n\na[x-apple-data-detectors=\'true\'] \\{\n  color: inherit !important;\n  text-decoration: none !important;\n}\n\n\n\ntable, td \\{ color: #000000; } #u_body a \\{ color: #0000ee; text-decoration: underline; }\n    </style>\n  \n  \n\n</head>\n\n<body class="clean-body u_body" style="margin: 0;padding: 0;-webkit-text-size-adjust: 100%;background-color: #F7F8F9;color: #000000">\n  <!--[if IE]><div class="ie-container"><![endif]-->\n  <!--[if mso]><div class="mso-container"><![endif]-->\n  <table id="u_body" style="border-collapse: collapse;table-layout: fixed;border-spacing: 0;mso-table-lspace: 0pt;mso-table-rspace: 0pt;vertical-align: top;min-width: 320px;Margin: 0 auto;background-color: #F7F8F9;width:100%" cellpadding="0" cellspacing="0">\n  <tbody>\n  <tr style="vertical-align: top">\n    <td style="word-break: break-word;border-collapse: collapse !important;vertical-align: top">\n    <!--[if (mso)|(IE)]><table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center" style="background-color: #F7F8F9;"><![endif]-->\n    \n  \n  \n<div class="u-row-container" style="padding: 0px;background-color: transparent">\n  <div class="u-row" style="margin: 0 auto;min-width: 320px;max-width: 500px;overflow-wrap: break-word;word-wrap: break-word;word-break: break-word;background-color: transparent;">\n    <div style="border-collapse: collapse;display: table;width: 100%;height: 100%;background-color: transparent;">\n      <!--[if (mso)|(IE)]><table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td style="padding: 0px;background-color: transparent;" align="center"><table cellpadding="0" cellspacing="0" border="0" style="width:500px;"><tr style="background-color: transparent;"><![endif]-->\n      \n<!--[if (mso)|(IE)]><td align="center" width="500" style="width: 500px;padding: 0px;border-top: 0px solid transparent;border-left: 0px solid transparent;border-right: 0px solid transparent;border-bottom: 0px solid transparent;border-radius: 0px;-webkit-border-radius: 0px; -moz-border-radius: 0px;" valign="top"><![endif]-->\n<div class="u-col u-col-100" style="max-width: 320px;min-width: 500px;display: table-cell;vertical-align: top;">\n  <div style="height: 100%;width: 100% !important;border-radius: 0px;-webkit-border-radius: 0px; -moz-border-radius: 0px;">\n  <!--[if (!mso)&(!IE)]><!--><div style="box-sizing: border-box; height: 100%; padding: 0px;border-top: 0px solid transparent;border-left: 0px solid transparent;border-right: 0px solid transparent;border-bottom: 0px solid transparent;border-radius: 0px;-webkit-border-radius: 0px; -moz-border-radius: 0px;"><!--<![endif]-->\n  \n<table style="font-family:arial,helvetica,sans-serif;" role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">\n  <tbody>\n    <tr>\n      <td style="overflow-wrap:break-word;word-break:break-word;padding:10px;font-family:arial,helvetica,sans-serif;" align="left">\n        \n  <div style="font-size: 14px; line-height: 140%; text-align: left; word-wrap: break-word;">\n    <p style="line-height: 140%;">Hello from PostHog!</p>\n  </div>\n\n      </td>\n    </tr>\n  </tbody>\n</table>\n\n<table style="font-family:arial,helvetica,sans-serif;" role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">\n  <tbody>\n    <tr>\n      <td style="overflow-wrap:break-word;word-break:break-word;padding:10px;font-family:arial,helvetica,sans-serif;" align="left">\n        \n  <!--[if mso]><style>.v-button \\{background: transparent !important;}</style><![endif]-->\n<div align="center">\n  <!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="https://posthog.com/" style="height:37px; v-text-anchor:middle; width:112px;" arcsize="11%"  stroke="f" fillcolor="#3AAEE0"><w:anchorlock/><center style="color:#FFFFFF;"><![endif]-->\n    <a href="https://posthog.com/" target="_blank" class="v-button" style="box-sizing: border-box;display: inline-block;text-decoration: none;-webkit-text-size-adjust: none;text-align: center;color: #FFFFFF; background-color: #3AAEE0; border-radius: 4px;-webkit-border-radius: 4px; -moz-border-radius: 4px; width:auto; max-width:100%; overflow-wrap: break-word; word-break: break-word; word-wrap:break-word; mso-border-alt: none;font-size: 14px;">\n      <span style="display:block;padding:10px 20px;line-height:120%;">Learn more</span>\n    </a>\n    <!--[if mso]></center></v:roundrect><![endif]-->\n</div>\n\n      </td>\n    </tr>\n  </tbody>\n</table>\n\n  <!--[if (!mso)&(!IE)]><!--></div><!--<![endif]-->\n  </div>\n</div>\n<!--[if (mso)|(IE)]></td><![endif]-->\n      <!--[if (mso)|(IE)]></tr></table></td></tr></table><![endif]-->\n    </div>\n  </div>\n  </div>\n  \n\n\n    <!--[if (mso)|(IE)]></td></tr></table><![endif]-->\n    </td>\n  </tr>\n  </tbody>\n  </table>\n  <!--[if mso]></div><![endif]-->\n  <!--[if IE]></div><![endif]-->\n\n\n\n</body></html>',
                "design": {
                    "body": {
                        "id": "TlJ2GekAva",
                        "rows": [
                            {
                                "id": "-sL7LJ6rhD",
                                "cells": [1],
                                "values": {
                                    "_meta": {"htmlID": "u_row_1", "htmlClassNames": "u_row"},
                                    "anchor": "",
                                    "columns": False,
                                    "padding": "0px",
                                    "hideable": True,
                                    "deletable": True,
                                    "draggable": True,
                                    "selectable": True,
                                    "_styleGuide": None,
                                    "hideDesktop": False,
                                    "duplicatable": True,
                                    "backgroundColor": "",
                                    "backgroundImage": {
                                        "url": "",
                                        "size": "custom",
                                        "repeat": "no-repeat",
                                        "position": "center",
                                        "fullWidth": True,
                                        "customPosition": ["50%", "50%"],
                                    },
                                    "displayCondition": None,
                                    "columnsBackgroundColor": "",
                                },
                                "columns": [
                                    {
                                        "id": "IT_J8vPWTn",
                                        "values": {
                                            "_meta": {"htmlID": "u_column_1", "htmlClassNames": "u_column"},
                                            "border": {},
                                            "padding": "0px",
                                            "borderRadius": "0px",
                                            "backgroundColor": "",
                                        },
                                        "contents": [
                                            {
                                                "id": "BSAz3H7CN9",
                                                "type": "text",
                                                "values": {
                                                    "text": '<p style="line-height: 140%;">Hello from PostHog!</p>',
                                                    "_meta": {
                                                        "htmlID": "u_content_text_1",
                                                        "htmlClassNames": "u_content_text",
                                                    },
                                                    "anchor": "",
                                                    "fontSize": "14px",
                                                    "hideable": True,
                                                    "deletable": True,
                                                    "draggable": True,
                                                    "linkStyle": {
                                                        "inherit": True,
                                                        "linkColor": "#0000ee",
                                                        "linkUnderline": True,
                                                        "linkHoverColor": "#0000ee",
                                                        "linkHoverUnderline": True,
                                                    },
                                                    "textAlign": "left",
                                                    "_languages": {},
                                                    "lineHeight": "140%",
                                                    "selectable": True,
                                                    "_styleGuide": None,
                                                    "duplicatable": True,
                                                    "containerPadding": "10px",
                                                    "displayCondition": None,
                                                },
                                            },
                                            {
                                                "id": "cAnEDJLdIg",
                                                "type": "button",
                                                "values": {
                                                    "href": {
                                                        "name": "web",
                                                        "attrs": {"href": "{{href}}", "target": "{{target}}"},
                                                        "values": {"href": "https://posthog.com/", "target": "_blank"},
                                                    },
                                                    "size": {"width": "100%", "autoWidth": True},
                                                    "text": "Learn more",
                                                    "_meta": {
                                                        "htmlID": "u_content_button_1",
                                                        "htmlClassNames": "u_content_button",
                                                    },
                                                    "anchor": "",
                                                    "border": {},
                                                    "padding": "10px 20px",
                                                    "fontSize": "14px",
                                                    "hideable": True,
                                                    "deletable": True,
                                                    "draggable": True,
                                                    "textAlign": "center",
                                                    "_languages": {},
                                                    "lineHeight": "120%",
                                                    "selectable": True,
                                                    "_styleGuide": None,
                                                    "borderRadius": "4px",
                                                    "buttonColors": {
                                                        "color": "#FFFFFF",
                                                        "hoverColor": "#FFFFFF",
                                                        "backgroundColor": "#3AAEE0",
                                                        "hoverBackgroundColor": "#3AAEE0",
                                                    },
                                                    "duplicatable": True,
                                                    "calculatedWidth": 112,
                                                    "calculatedHeight": 37,
                                                    "containerPadding": "10px",
                                                    "displayCondition": None,
                                                },
                                            },
                                        ],
                                    }
                                ],
                            }
                        ],
                        "values": {
                            "_meta": {"htmlID": "u_body", "htmlClassNames": "u_body"},
                            "language": {},
                            "linkStyle": {
                                "body": True,
                                "linkColor": "#0000ee",
                                "linkUnderline": True,
                                "linkHoverColor": "#0000ee",
                                "linkHoverUnderline": True,
                            },
                            "textColor": "#000000",
                            "fontFamily": {"label": "Arial", "value": "arial,helvetica,sans-serif"},
                            "popupWidth": "600px",
                            "_styleGuide": None,
                            "popupHeight": "auto",
                            "borderRadius": "10px",
                            "contentAlign": "center",
                            "contentWidth": "500px",
                            "popupPosition": "center",
                            "preheaderText": "",
                            "backgroundColor": "#F7F8F9",
                            "backgroundImage": {
                                "url": "",
                                "size": "custom",
                                "repeat": "no-repeat",
                                "position": "center",
                                "fullWidth": True,
                            },
                            "contentVerticalAlign": "center",
                            "popupBackgroundColor": "#FFFFFF",
                            "popupBackgroundImage": {
                                "url": "",
                                "size": "cover",
                                "repeat": "no-repeat",
                                "position": "center",
                                "fullWidth": True,
                            },
                            "popupCloseButton_action": {
                                "name": "close_popup",
                                "attrs": {
                                    "onClick": "document.querySelector('.u-popup-container').style.display = 'none';"
                                },
                            },
                            "popupCloseButton_margin": "0px",
                            "popupCloseButton_position": "top-right",
                            "popupCloseButton_iconColor": "#000000",
                            "popupOverlay_backgroundColor": "rgba(0, 0, 0, 0.1)",
                            "popupCloseButton_borderRadius": "0px",
                            "popupCloseButton_backgroundColor": "#DDDDDD",
                        },
                        "footers": [],
                        "headers": [],
                    },
                    "counters": {"u_row": 1, "u_column": 1, "u_content_text": 1, "u_content_button": 1},
                    "schemaVersion": 17,
                },
            },
            "secret": False,
            "required": True,
        },
    ],
    filters={
        "properties": [{"key": "email", "value": "is_set", "operator": "is_set", "type": "person"}],
    },
)
