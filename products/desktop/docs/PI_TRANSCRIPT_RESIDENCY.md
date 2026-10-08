# Pi transcript residency

Pi releases transcript events and model catalogs when a view leaves an idle session.
The next visit reloads history through the session provider, as it does for an initial visit.
Usage stats and recovery errors remain available without retaining the transcript.
Session status is released too, so the next visit shows the loading skeleton instead of an empty conversation.

Background sessions stay subscribed while a submission, turn, compaction, shell command, authentication restoration, queue, or permission request needs them.
A submission holds the session from the moment the user sends it, before the runtime reports the turn.
A cloud run stays subscribed until its status is terminal.
A queue or a permission request left behind by a finished cloud run does not hold the session, because that run can no longer act on it.
Once the remaining work finishes, the controller releases the inactive transcript.
Disconnecting all sessions also releases all stored transcripts.

The controller lifecycle tests cover reopening evicted history and keeping unfinished background work alive.
For a memory check, repeatedly open and leave completed Pi tasks and collect renderer garbage after the run.
Idle transcript retention should stay flat as the number of visited tasks grows.
