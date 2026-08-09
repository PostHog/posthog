import { resolveTextCommentAnchor } from "@posthog/core/comments/anchors";
import {
  COMMENT_ACTION_BUTTON_THEMES,
  COMMENT_ACTION_ICON_SVG,
  type CommentSurfaceTheme,
  commentActionAnchorRect,
  commentActionButtonCss,
  computeCommentActionPlacement,
  installSelectionSettleGate,
  setCommentActionTheme,
} from "./selectionCommentAction";

const BRIDGE_MARKER = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";

/**
 * Runs inside the isolated artifact document. It never receives credentials
 * or writes to the API; selection traffic uses a per-view host channel.
 */
function artifactHtmlCommentBridge(
  channel: string,
  theme: CommentSurfaceTheme,
  nonce?: string,
): string {
  const safeChannel = JSON.stringify(channel);
  const nonceAttribute = nonce ? ` nonce="${nonce}"` : "";
  return `<script${nonceAttribute} data-posthog-artifact-comments>(function(){
"use strict";
var CHANNEL=${safeChannel};
var MARKER=${JSON.stringify(BRIDGE_MARKER)};
var state={button:null,timer:0,renderTimer:0,entries:[],items:[],theme:${JSON.stringify(theme)}};
var supportsHighlights=!!(window.Highlight&&window.CSS&&CSS.highlights);
var current=document.currentScript;if(current)current.remove();
function send(type,payload){parent.postMessage(Object.assign({marker:MARKER,channel:CHANNEL,type:type},payload||{}),"*");}
function text(){return (document.body&&document.body.textContent)||"";}
function offsets(range){var a=document.createRange(),b=document.createRange();a.selectNodeContents(document.body);a.setEnd(range.startContainer,range.startOffset);b.selectNodeContents(document.body);b.setEnd(range.endContainer,range.endOffset);return{start:a.toString().length,end:b.toString().length};}
function makeAnchor(range){var all=text(),o=offsets(range),quote=all.slice(o.start,o.end);if(!quote.trim()||quote.length>10000)return null;return{kind:"text",quote:quote,prefix:all.slice(Math.max(0,o.start-32),o.start),suffix:all.slice(o.end,o.end+32),start:o.start,end:o.end};}
function textIndex(){var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),n,all="",entries=[];while((n=w.nextNode())){var start=all.length;all+=n.data;entries.push({node:n,start:start,end:all.length})}return{text:all,entries:entries}}
function rangeAt(index,start,end){function find(offset){var low=0,high=index.entries.length-1,match=null;while(low<=high){var middle=(low+high)>>1,entry=index.entries[middle];if(offset<entry.start)high=middle-1;else if(offset>entry.end)low=middle+1;else{match=entry;high=middle-1}}return match}var sn=find(start),en=find(end);if(!sn||!en)return null;try{var r=document.createRange();r.setStart(sn.node,start-sn.start);r.setEnd(en.node,end-en.start);return r}catch(e){return null}}
var THEMES=${JSON.stringify(COMMENT_ACTION_BUTTON_THEMES)};
var ACTION_ICON=${JSON.stringify(COMMENT_ACTION_ICON_SVG)};
var setActionTheme=${setCommentActionTheme.toString()};
var placeAction=${computeCommentActionPlacement.toString()};
var anchorRect=${commentActionAnchorRect.toString()};
var resolveAnchor=${resolveTextCommentAnchor.toString()};
function resolve(all,a){return resolveAnchor(all,a)}
function style(){var s=document.createElement("style");s.setAttribute("data-posthog-artifact-comments","");s.textContent="::highlight(posthog-artifact-comment){background:rgba(250,204,21,.32);color:inherit}::highlight(posthog-artifact-comment-active){background:rgba(250,204,21,.48);color:inherit}";(document.head||document.documentElement).appendChild(s)}
function hide(){if(state.button)state.button.style.display="none"}
function button(){if(state.button&&state.button.isConnected)return state.button;var host=document.createElement("posthog-comment-action");host.setAttribute("data-selection-comment-overlay","");host.style.cssText="all:initial!important;display:block!important;position:fixed!important;top:0!important;left:0!important;width:0!important;height:0!important;overflow:visible!important;z-index:2147483647!important";var root=host.attachShadow({mode:"open"});var s=document.createElement("style");s.textContent=${JSON.stringify(commentActionButtonCss())};root.appendChild(s);var b=document.createElement("button");b.type="button";b.className="ph-comment-action-button";b.setAttribute("aria-label","Comment");b.innerHTML=ACTION_ICON+"<span>Comment</span>";setActionTheme(state.theme,THEMES,b);b.style.display="none";b.addEventListener("mousedown",function(e){e.preventDefault();e.stopPropagation();var sel=window.getSelection();if(!sel||sel.isCollapsed||!sel.rangeCount)return hide();var range=sel.getRangeAt(0),anchor=makeAnchor(range);if(!anchor)return hide();var r=range.getBoundingClientRect(),br=b.getBoundingClientRect();send("selection",{anchor:anchor,rect:{top:r.top,left:r.left,right:r.right,bottom:r.bottom,width:r.width,height:r.height},triggerRect:{top:br.top,left:br.left,right:br.right,bottom:br.bottom,width:br.width,height:br.height}});hide();sel.removeAllRanges()});root.appendChild(b);document.documentElement.appendChild(host);state.button=b;return b;}
function positionButton(){var sel=window.getSelection();if(!sel||sel.isCollapsed||!sel.rangeCount)return hide();var value=sel.toString().trim();if(value.length<2||value.length>10000)return hide();var range=sel.getRangeAt(0);var r=anchorRect(range.getClientRects?range.getClientRects():[],range.getBoundingClientRect());if(!r||(r.width===0&&r.height===0))return hide();var b=button();var box=b.getBoundingClientRect();var pos=placeAction({top:r.top,right:r.right,bottom:r.bottom},{width:innerWidth,height:innerHeight},{width:box.width||104,height:box.height||28});b.style.left=pos.left+"px";b.style.top=pos.top+"px";b.style.display="flex"}
function selectionChanged(){clearTimeout(state.timer);state.timer=setTimeout(positionButton,80)}
function render(items){state.items=items||[];state.entries=[];var normal=supportsHighlights?new Highlight():null,active=supportsHighlights?new Highlight():null,resolutions=[],index=textIndex();state.items.forEach(function(item){var hit=resolve(index.text,item.anchor);if(!hit){resolutions.push({id:item.id,status:"orphaned"});return}var range=rangeAt(index,hit.start,hit.end);if(!range){resolutions.push({id:item.id,status:"orphaned"});return}state.entries.push({id:item.id,range:range,active:!!item.active});resolutions.push({id:item.id,status:hit.status});if(supportsHighlights){if(item.active)active.add(range);else normal.add(range)}});if(supportsHighlights){CSS.highlights.set("posthog-artifact-comment",normal);CSS.highlights.set("posthog-artifact-comment-active",active)}send("resolutions",{items:resolutions})}
function locate(id){for(var i=0;i<state.entries.length;i++){if(state.entries[i].id!==id)continue;var node=state.entries[i].range.startContainer,parentNode=node.nodeType===1?node:node.parentElement;if(parentNode&&parentNode.scrollIntoView)parentNode.scrollIntoView({behavior:"smooth",block:"center"});return}}
// Report the selection only once it settles, so the button doesn't chase the
// cursor mid-drag. The settle callback re-reads the live selection, which
// self-corrects clicks that didn't change the selection.
var selectionSettleGate=${installSelectionSettleGate.toString()};
selectionSettleGate(document,{onGestureStart:hide,onSelectionSettled:positionButton,onIdleSelectionChange:selectionChanged,onGestureCancel:hide});
document.addEventListener("scroll",hide,true);
document.addEventListener("click",function(e){var target=e.target,link=target&&target.closest?target.closest("a[href]"):null;if(link){e.preventDefault();e.stopPropagation();send("open-external",{href:link.href});return}for(var i=0;i<state.entries.length;i++){var rects=state.entries[i].range.getClientRects();for(var j=0;j<rects.length;j++){var r=rects[j];if(e.clientX>=r.left&&e.clientX<=r.right&&e.clientY>=r.top&&e.clientY<=r.bottom){e.preventDefault();e.stopPropagation();send("activate",{id:state.entries[i].id});return}}}},true);
new MutationObserver(function(){if(!state.items.length||state.renderTimer)return;state.renderTimer=setTimeout(function(){state.renderTimer=0;render(state.items)},500)}).observe(document.body,{childList:true,characterData:true,subtree:true});
window.addEventListener("message",function(e){if(e.source!==parent)return;var d=e.data;if(!d||d.marker!==MARKER||d.channel!==CHANNEL)return;if(d.type==="comments")render(d.items);else if(d.type==="locate"&&typeof d.id==="string")locate(d.id);else if(d.type==="theme"&&(d.theme==="light"||d.theme==="dark")){state.theme=d.theme;if(state.button)setActionTheme(d.theme,THEMES,state.button)}});
style();send("ready");
})();</script>`;
}

export function injectArtifactHtmlCommentBridge(
  html: string,
  options: {
    channel: string;
    theme: CommentSurfaceTheme;
    nonce?: string;
  },
): string {
  const bridge = artifactHtmlCommentBridge(
    options.channel,
    options.theme,
    options.nonce,
  );
  const bodyEnd = html.toLowerCase().lastIndexOf("</body>");
  if (bodyEnd >= 0) {
    return `${html.slice(0, bodyEnd)}${bridge}${html.slice(bodyEnd)}`;
  }
  const htmlEnd = html.toLowerCase().lastIndexOf("</html>");
  if (htmlEnd >= 0) {
    return `${html.slice(0, htmlEnd)}${bridge}${html.slice(htmlEnd)}`;
  }
  return `${html}${bridge}`;
}
