import { resolveTextCommentAnchor } from "@posthog/core/comments/anchors";

const BRIDGE_MARKER = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";

/**
 * Runs inside an opaque-origin sandboxed artifact iframe. It never receives
 * credentials or writes to the API: selection and highlight traffic goes
 * through the trusted parent with a per-view channel.
 */
function artifactHtmlCommentBridge(channel: string, nonce: string): string {
  const safeChannel = JSON.stringify(channel);
  return `<script nonce="${nonce}" data-posthog-artifact-comments>(function(){
"use strict";
var CHANNEL=${safeChannel};
var MARKER=${JSON.stringify(BRIDGE_MARKER)};
var state={button:null,timer:0,renderTimer:0,entries:[],items:[]};
var supportsHighlights=!!(window.Highlight&&window.CSS&&CSS.highlights);
var current=document.currentScript;if(current)current.remove();
function send(type,payload){parent.postMessage(Object.assign({marker:MARKER,channel:CHANNEL,type:type},payload||{}),"*");}
function text(){return (document.body&&document.body.textContent)||"";}
function offsets(range){var a=document.createRange(),b=document.createRange();a.selectNodeContents(document.body);a.setEnd(range.startContainer,range.startOffset);b.selectNodeContents(document.body);b.setEnd(range.endContainer,range.endOffset);return{start:a.toString().length,end:b.toString().length};}
function makeAnchor(range){var all=text(),o=offsets(range),quote=all.slice(o.start,o.end);if(!quote.trim()||quote.length>10000)return null;return{kind:"text",quote:quote,prefix:all.slice(Math.max(0,o.start-32),o.start),suffix:all.slice(o.end,o.end+32),start:o.start,end:o.end};}
function textIndex(){var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),n,all="",entries=[];while((n=w.nextNode())){var start=all.length;all+=n.data;entries.push({node:n,start:start,end:all.length})}return{text:all,entries:entries}}
function rangeAt(index,start,end){function find(offset){var low=0,high=index.entries.length-1,match=null;while(low<=high){var middle=(low+high)>>1,entry=index.entries[middle];if(offset<entry.start)high=middle-1;else if(offset>entry.end)low=middle+1;else{match=entry;high=middle-1}}return match}var sn=find(start),en=find(end);if(!sn||!en)return null;try{var r=document.createRange();r.setStart(sn.node,start-sn.start);r.setEnd(en.node,end-en.start);return r}catch(e){return null}}
var resolveAnchor=${resolveTextCommentAnchor.toString()};
function resolve(all,a){return resolveAnchor(all,a)}
function style(){var s=document.createElement("style");s.setAttribute("data-posthog-artifact-comments","");s.textContent="::highlight(posthog-artifact-comment){background:rgba(250,204,21,.32);color:inherit}::highlight(posthog-artifact-comment-active){background:rgba(250,204,21,.48);color:inherit}.ph-artifact-comment-button{position:fixed;z-index:2147483647;display:flex;align-items:center;gap:6px;height:34px;padding:0 13px;border:1px solid #ca8a04;border-radius:9px;background:#facc15;color:#1c1917;font:600 13px/1 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;box-shadow:0 3px 12px rgba(0,0,0,.3);cursor:pointer}.ph-artifact-comment-button:hover{background:#fde047}";(document.head||document.documentElement).appendChild(s)}
function hide(){if(state.button)state.button.style.display="none"}
function button(){if(state.button&&state.button.isConnected)return state.button;var b=document.createElement("button");b.type="button";b.className="ph-artifact-comment-button";b.textContent="💬 Comment";b.style.display="none";b.addEventListener("mousedown",function(e){e.preventDefault();e.stopPropagation();var sel=window.getSelection();if(!sel||sel.isCollapsed||!sel.rangeCount)return hide();var range=sel.getRangeAt(0),anchor=makeAnchor(range);if(!anchor)return hide();var r=range.getBoundingClientRect(),br=b.getBoundingClientRect();send("selection",{anchor:anchor,rect:{top:r.top,left:r.left,right:r.right,bottom:r.bottom,width:r.width,height:r.height},triggerRect:{top:br.top,left:br.left,right:br.right,bottom:br.bottom,width:br.width,height:br.height}});hide();sel.removeAllRanges()});document.documentElement.appendChild(b);state.button=b;return b;}
function selectionChanged(){clearTimeout(state.timer);state.timer=setTimeout(function(){var sel=window.getSelection();if(!sel||sel.isCollapsed||!sel.rangeCount)return hide();var value=sel.toString().trim();if(value.length<2||value.length>10000)return hide();var r=sel.getRangeAt(0).getBoundingClientRect();if(!r||(r.width===0&&r.height===0))return hide();var b=button();b.style.left=Math.max(8,Math.min(innerWidth-110,r.left+r.width/2-50))+"px";b.style.top=Math.max(8,r.top-42)+"px";b.style.display="flex"},80)}
function render(items){state.items=items||[];state.entries=[];var normal=supportsHighlights?new Highlight():null,active=supportsHighlights?new Highlight():null,resolutions=[],index=textIndex();state.items.forEach(function(item){var hit=resolve(index.text,item.anchor);if(!hit){resolutions.push({id:item.id,status:"orphaned"});return}var range=rangeAt(index,hit.start,hit.end);if(!range){resolutions.push({id:item.id,status:"orphaned"});return}state.entries.push({id:item.id,range:range,active:!!item.active});resolutions.push({id:item.id,status:hit.status});if(supportsHighlights){if(item.active)active.add(range);else normal.add(range)}});if(supportsHighlights){CSS.highlights.set("posthog-artifact-comment",normal);CSS.highlights.set("posthog-artifact-comment-active",active)}send("resolutions",{items:resolutions})}
function locate(id){for(var i=0;i<state.entries.length;i++){if(state.entries[i].id!==id)continue;var node=state.entries[i].range.startContainer,parentNode=node.nodeType===1?node:node.parentElement;if(parentNode&&parentNode.scrollIntoView)parentNode.scrollIntoView({behavior:"smooth",block:"center"});return}}
document.addEventListener("selectionchange",selectionChanged);
document.addEventListener("scroll",hide,true);
document.addEventListener("click",function(e){var target=e.target,link=target&&target.closest?target.closest("a[href]"):null;if(link){e.preventDefault();e.stopPropagation();send("open-external",{href:link.href});return}for(var i=0;i<state.entries.length;i++){var rects=state.entries[i].range.getClientRects();for(var j=0;j<rects.length;j++){var r=rects[j];if(e.clientX>=r.left&&e.clientX<=r.right&&e.clientY>=r.top&&e.clientY<=r.bottom){e.preventDefault();e.stopPropagation();send("activate",{id:state.entries[i].id});return}}}},true);
new MutationObserver(function(){if(!state.items.length||state.renderTimer)return;state.renderTimer=setTimeout(function(){state.renderTimer=0;render(state.items)},500)}).observe(document.body,{childList:true,characterData:true,subtree:true});
window.addEventListener("message",function(e){if(e.source!==parent)return;var d=e.data;if(!d||d.marker!==MARKER||d.channel!==CHANNEL)return;if(d.type==="comments")render(d.items);else if(d.type==="locate"&&typeof d.id==="string")locate(d.id)});
style();send("ready");
})();</script>`;
}

export function injectArtifactHtmlCommentBridge(
  html: string,
  channel: string,
  nonce: string,
): string {
  const bridge = artifactHtmlCommentBridge(channel, nonce);
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
