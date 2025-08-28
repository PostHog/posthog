package com.example.backend.jobs;

import com.example.backend.services.ReportService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

@Service
public class SendDataJob {
    private final ReportService reportService;

    @Autowired
    public SendDataJob(ReportService reportService) {
        this.reportService = reportService;
    }

//    @Override
    @Scheduled(cron = "*/30 * * * * *", zone = "Asia/Hebron")
    public void run() {
        System.out.println("Ready to Send data");
        reportService.emailEventsAndHeatmaps();
        System.out.println("data Sent");
    }
}
